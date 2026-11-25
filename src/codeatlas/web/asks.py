"""Questions asked from the web app: the agent runs on a background thread, one at a time.

An answer takes from a few seconds to a minute or more: every step is a call to a
language model. So, as with indexing (`jobs.py`), the page that asks gets an id back at
once and the answer page reloads every two seconds, showing each step as it finishes.

One question runs at a time because the free model tiers limit tokens per minute: two
answers made together would only make both run into the limit.

Questions live in memory only (the owner's choice, Nov 17). Each one's full record is
also the agent's trajectory file on disk, which outlives the server.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from codeatlas.agent.loop import Answer, OnStep
from codeatlas.llm.client import OnWait
from codeatlas.web.markdown import render_answer

MAX_QUESTION_CHARS = 2000
MAX_WAITING = 3  # one running and two waiting
MAX_KEPT = 30

# What a question runs: (snapshot id, question, on_step, on_wait) -> the agent's answer.
Work = Callable[[str, str, OnStep, OnWait], Answer]


class TooManyQuestions(Exception):
    """Enough questions are waiting already."""


class Stopped(Exception):
    """The person asked to stop; raised between the agent's steps."""


@dataclass(slots=True)
class Question:
    """One question about one snapshot, and where its answer has got to."""

    id: str
    snapshot_id: str
    text: str
    state: str = "waiting"  # waiting, running, done, failed
    steps: list[dict[str, Any]] = field(default_factory=list)  # trajectory records so far
    # Each time every model was rate limited: {"seconds", "provider", "until"}.
    waits: list[dict[str, Any]] = field(default_factory=list)
    answer: Answer | None = None
    error: str = ""
    stop_requested: bool = False
    created: float = field(default_factory=time.monotonic)
    started: float | None = None
    finished: float | None = None

    @property
    def active(self) -> bool:
        return self.state in ("waiting", "running")

    @property
    def seconds(self) -> float:
        if self.started is None:
            return 0.0
        return (self.finished or time.monotonic()) - self.started

    def record_step(self, record: dict[str, Any]) -> None:
        """Called by the agent after each step. A finished answer is never thrown away."""
        self.steps.append(record)
        if not record.get("final"):
            self.check_stop()

    def record_wait(self, seconds: float, provider: str) -> None:
        """Called by the LLM client just before it waits out a rate limit."""
        self.check_stop()
        self.waits.append({"seconds": seconds, "provider": provider,
                           "until": time.monotonic() + seconds})

    def check_stop(self) -> None:
        if self.stop_requested:
            raise Stopped("Stopped.")

    @property
    def waiting_now(self) -> dict[str, Any] | None:
        """The wait in progress, with the seconds left, or None."""
        if not self.waits or self.state != "running":
            return None
        left = self.waits[-1]["until"] - time.monotonic()
        return {**self.waits[-1], "left": left} if left > 0 else None

    @property
    def seconds_waited(self) -> float:
        return sum(w["seconds"] for w in self.waits)

    @property
    def tokens(self) -> tuple[int, int]:
        """Input and output tokens of the steps so far."""
        return (sum(s.get("input_tokens", 0) for s in self.steps),
                sum(s.get("output_tokens", 0) for s in self.steps))


class Questions:
    """Starts questions, runs them one after another, and remembers the recent ones."""

    def __init__(self, work: Work) -> None:
        self._work = work
        self._questions: dict[str, Question] = {}
        self._lock = threading.Lock()  # guards the dictionary
        self._turn = threading.Lock()  # held by the one question being answered

    def start(self, snapshot_id: str, text: str) -> Question:
        with self._lock:
            if sum(1 for q in self._questions.values() if q.active) >= MAX_WAITING:
                raise TooManyQuestions(f"{MAX_WAITING} questions are already waiting for "
                                       "an answer: ask again when one has finished")
            question = Question(uuid.uuid4().hex[:12], snapshot_id, text)
            self._questions[question.id] = question
            self._forget_old()
        threading.Thread(target=self._run, args=(question,), daemon=True, name="ask").start()
        return question

    def get(self, question_id: str) -> Question | None:
        with self._lock:
            return self._questions.get(question_id)

    def stop(self, question_id: str) -> None:
        """Ask a question to stop. It does so between steps: a request to a model that
        is already under way is waited for, and nothing is cut in the middle."""
        question = self.get(question_id)
        if question is not None and question.active:
            question.stop_requested = True

    def recent(self, snapshot_id: str) -> list[Question]:
        """This snapshot's questions, newest first."""
        with self._lock:
            mine = [q for q in self._questions.values() if q.snapshot_id == snapshot_id]
        return sorted(mine, key=lambda q: q.created, reverse=True)

    def wait(self, question_id: str, timeout: float = 60.0) -> Question:
        """Block until a question is answered. For tests; pages never wait."""
        end = time.monotonic() + timeout
        question = self.get(question_id)
        assert question is not None, question_id
        while question.active and time.monotonic() < end:
            time.sleep(0.02)
        return question

    def _run(self, question: Question) -> None:
        with self._turn:
            question.state, question.started = "running", time.monotonic()
            try:
                question.check_stop()  # stopped while it waited its turn
                answer = self._work(question.snapshot_id, question.text,
                                    question.record_step, question.record_wait)
            except Exception as exc:  # a question must end as "failed", never vanish
                question.error = str(exc) or type(exc).__name__
                question.finished = time.monotonic()
                question.state = "failed"
                return
            # The answer before the state: a page that reads "done" relies on the answer
            # being there already (`answer_page` in app.py).
            question.answer = answer
            question.finished = time.monotonic()
            question.state = "done"

    def _forget_old(self) -> None:
        finished = sorted((q for q in self._questions.values() if not q.active),
                          key=lambda q: q.created)
        for question in finished[: max(0, len(finished) - MAX_KEPT)]:
            del self._questions[question.id]


def step_rows(question: Question) -> list[dict[str, Any]]:
    """One row per tool call made so far, for the answer page."""
    rows = []
    for record in question.steps:
        for call in record.get("tool_calls", []):
            args = ", ".join(f"{k}={v!r}" for k, v in (call.get("arguments") or {}).items())
            rows.append({"step": record["step"], "tool": call["name"], "arguments": args,
                         "chars": call.get("result_chars", 0),
                         "repeat_of": call.get("repeat_of")})
    return rows


def chat_message(question: Question, base: str) -> dict[str, Any]:
    """One question as the chat shows it. The state is read once, before everything else:
    the question's thread may finish meanwhile, and "done" means the answer is there."""
    state = question.state
    out: dict[str, Any] = {
        "id": question.id, "text": question.text, "state": state, "error": question.error,
        "rows": step_rows(question), "step_count": len(question.steps),
        "wait": question.waiting_now, "stopping": question.stop_requested,
    }
    answer = question.answer if state == "done" else None
    if answer is not None:
        steps = f"{answer.steps} step{'' if answer.steps == 1 else 's'}"
        out.update(html=render_answer(answer, base), warning=_warning(answer),
                   summary=f"{steps}, {question.seconds:.0f} s, {answer.input_tokens:,} tokens, "
                           f"{_cited(answer)}")
    return out


def _cited(answer: Answer) -> str:
    n = len(answer.citations)
    return f"{n} citation{'' if n == 1 else 's'} checked"


def _warning(answer: Answer) -> str:
    """What the reader must know before trusting an answer, or an empty string."""
    bad = len(answer.invalid_citations)
    if not answer.citations:
        return "This answer cites nothing, so none of it was checked against the code."
    if bad:
        return (f"{bad} of {len(answer.citations)} citations point at no real place. "
                "They are marked.")
    return ""
