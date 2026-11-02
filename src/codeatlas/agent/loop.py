"""The agent loop: ask the model, run its tool calls, repeat, then check its citations."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codeatlas.agent.prompts import system_prompt
from codeatlas.agent.tools import ToolSet
from codeatlas.config import Config
from codeatlas.llm import LLMClient, Message

# repo@sha12:path:line. The path may not contain a colon or whitespace; trailing
# punctuation such as `)` or `.` is not part of a citation.
_CITATION = re.compile(r"[\w.\-]+@[0-9a-f]{12}:[^\s:`'\"()\[\]<>,;]+:\d+")
LIMIT_NOTE = "(Step limit of {n} reached: this answer uses only what was found so far.)"
LIMIT_PROMPT = (
    "The step limit is reached. Answer now with what you know, without calling tools, and "
    "say that the step limit was hit."
)


@dataclass(frozen=True, slots=True)
class CitationCheck:
    """One citation found in an answer, and whether it points at a real place."""

    text: str
    path: str
    line: int
    valid: bool
    reason: str = ""


@dataclass(slots=True)
class Answer:
    """The model's answer plus everything needed to judge and replay it."""

    text: str
    citations: list[CitationCheck] = field(default_factory=list)
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    limit_hit: bool = False
    trajectory_path: Path | None = None

    @property
    def invalid_citations(self) -> list[CitationCheck]:
        return [c for c in self.citations if not c.valid]


def check_citations(text: str, tools: ToolSet) -> list[CitationCheck]:
    """Validate every citation in `text`: right snapshot, a file of it, a line inside it.

    "Inside" means within the file's module span, so a line past the end of the file is
    reported rather than silently accepted. Invalid citations are returned, never dropped.
    """
    store, snapshot_id = tools.context.store, tools.context.snapshot_id
    checks: list[CitationCheck] = []
    seen: set[str] = set()
    for match in _CITATION.finditer(text):
        citation = match.group(0)
        if citation in seen:
            continue
        seen.add(citation)
        sha_and_path, _, line_text = citation.rpartition(":")
        line = int(line_text)
        prefix = snapshot_id + ":"
        if not citation.startswith(prefix):
            checks.append(CitationCheck(citation, "", line, False,
                                        f"not from snapshot {snapshot_id}"))
            continue
        path = sha_and_path[len(prefix):]
        module = store.module_for_path(snapshot_id, path)
        if module is None:
            checks.append(CitationCheck(citation, path, line, False, "no such file"))
        elif not module.span.start_line <= line <= module.span.end_line:
            checks.append(CitationCheck(
                citation, path, line, False,
                f"line outside the file (1-{module.span.end_line})"))
        else:
            checks.append(CitationCheck(citation, path, line, True))
    return checks


def ask(
    question: str,
    store: Any,
    snapshot_id: str,
    client: LLMClient,
    max_steps: int = 20,
    data_dir: str | Path | None = None,
    config: Config | None = None,
) -> Answer:
    """Answer `question` about one snapshot; write a trajectory file; check citations."""
    config = config or Config()
    tools = ToolSet(store, snapshot_id, config)
    snapshot = tools.context.snapshot
    messages = [
        Message("system", system_prompt(store, snapshot, tools.specs)),
        Message("user", question),
    ]
    answer = Answer(text="")
    log: list[dict[str, Any]] = []
    try:
        _run(messages, tools, client, max_steps, answer, log)
        answer.citations = check_citations(answer.text, tools)
        if log:
            log[-1]["invalid_citations"] = [c.text for c in answer.invalid_citations]
    finally:
        answer.trajectory_path = _write_trajectory(
            Path(data_dir if data_dir is not None else config.data_dir), log)
    return answer


def _run(messages: list[Message], tools: ToolSet, client: LLMClient, max_steps: int,
         answer: Answer, log: list[dict[str, Any]]) -> None:
    for step in range(1, max_steps + 1):
        response, seconds = _timed_chat(client, messages, tools.specs)
        answer.steps = step
        answer.input_tokens += response.input_tokens
        answer.output_tokens += response.output_tokens
        messages.append(Message("assistant", response.text, tool_calls=response.tool_calls))
        record = _step_record(step, response, seconds)
        if step == 1:
            record["question"] = messages[1].content
        log.append(record)
        if not response.tool_calls:
            answer.text = response.text
            record["final"] = True
            return
        for call in response.tool_calls:
            result = tools.call_json(call.name, call.arguments)
            messages.append(Message("tool", result, tool_call_id=call.id))
            record["tool_calls"].append({"name": call.name, "arguments": call.arguments,
                                         "result_chars": len(result)})
    _finish_at_limit(messages, client, max_steps, answer, log)


def _finish_at_limit(messages: list[Message], client: LLMClient, max_steps: int,
                     answer: Answer, log: list[dict[str, Any]]) -> None:
    """One last call without tools, so the user gets what is known and is told the limit hit."""
    messages.append(Message("user", LIMIT_PROMPT))
    response, seconds = _timed_chat(client, messages, None)
    answer.steps += 1
    answer.input_tokens += response.input_tokens
    answer.output_tokens += response.output_tokens
    answer.limit_hit = True
    answer.text = f"{response.text}\n\n{LIMIT_NOTE.format(n=max_steps)}".strip()
    record = _step_record(answer.steps, response, seconds)
    record.update({"final": True, "limit_hit": True})
    log.append(record)


def _timed_chat(client: LLMClient, messages: list[Message], specs: Any) -> tuple[Any, float]:
    started = time.monotonic()
    response = client.chat(messages, specs)
    return response, round(time.monotonic() - started, 3)


def _step_record(step: int, response: Any, seconds: float) -> dict[str, Any]:
    return {
        "event": "step",
        "step": step,
        "seconds": seconds,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "provider": response.provider,
        "model": response.model,
        "text": response.text,
        "tool_calls": [],
    }


def _write_trajectory(data_dir: Path, log: list[dict[str, Any]]) -> Path:
    """`<data_dir>/trajectories/<UTC time>.jsonl`: exactly one JSON line per step."""
    folder = data_dir / "trajectories"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = folder / f"{stamp}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for record in log:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path
