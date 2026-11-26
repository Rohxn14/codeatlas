"""The agent loop: ask the model, run its tool calls, repeat, then check its citations."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codeatlas.agent.history import Exchange, with_history
from codeatlas.agent.leads import leads_text, look_up
from codeatlas.agent.prompts import system_prompt
from codeatlas.agent.quotes import QuoteCheck, check_quotes
from codeatlas.agent.tools import ToolSet
from codeatlas.config import Config
from codeatlas.llm import LLMClient, Message, ToolCall

# Citations are written repo@sha12:path:line (contract section 4). The path may not
# contain a colon or whitespace; trailing punctuation such as `)` or `.` is not part of a
# citation. Answers also hold shapes the contract does not ask for, and those are found
# and checked rather than skipped (all seen on Nov 19): a range (`:588-600`, also with a
# non-breaking hyphen or an en dash), a file with no line, a bare `path/file.py:276`, and
# a symbol's key (`path/file.py::build_silver`), which points at the symbol's first line.
_PATH = r"[^\s:`'\"()\[\]<>,;]+"
_DASHES = "-" + chr(0x2011) + chr(0x2013)  # hyphen, non-breaking hyphen, en dash
_RANGE = "(?:[" + _DASHES + r"](?P<{}>\d+))?"
_NAME = r"[A-Za-z_](?:[\w.]*\w)?"  # a qualname, never ending in a full stop
_BARE = (r"(?<![\w@./:-])(?P<bpath>[\w.\-]+(?:/[\w.\-]+)*\.[A-Za-z0-9]+)"
         r"(?:::(?P<bname>" + _NAME + r")|:(?P<bline>\d+)" + _RANGE.format("bend") + r"(?!\d))")
# Called with each step's trajectory record once its tool calls have run, so a page
# can show the steps while the answer is still being made.
OnStep = Callable[[dict[str, Any]], None]
LIMIT_NOTE = "(Step limit of {n} reached: this answer uses only what was found so far.)"
# Every request re-sends the whole conversation, so tool results pile up: on one real
# question (Nov 18) the input grew from 1,841 to 7,660 tokens over nine steps. The model
# sees the results of the last FULL_RESULT_STEPS steps whole; an older result longer than
# OLD_RESULT_CHARS is sent as the places it named (`_shortened`). The trajectory keeps
# every result whole.
FULL_RESULT_STEPS = 2
OLD_RESULT_CHARS = 400
# Kept as they are in a shortened result: what was asked, and whether there was more.
KEPT_FIELDS = ("query", "direction", "depth", "total", "truncated")
PLACES_NOTE = "older result shortened from {n} characters to the places it named"
# For a result that names no places: its first OLD_RESULT_CHARS characters, and this.
SHORTENED_NOTE = ("\n[older result shortened from {n} characters; call the tool again "
                  "to see all of it]")
# The tools read one fixed snapshot, so a call made again with the same arguments gets
# the same result. On Nov 19 the model still repeated 4 of 23 calls over two questions:
# twice with the first result in plain view, twice after SHORTENED_NOTE had cut it. A
# repeat is not run again. While the first result is still shown whole, the repeat gets
# only this note; once it has been cut, the repeat gets it whole again, with the note.
REPEAT_NOTE = ("Same tool and arguments as step {step}: the result has not changed. "
               "Work from that result, or answer.")
LIMIT_PROMPT = (
    "The step limit is reached. Answer now with what you know, without calling tools, and "
    "say that the step limit was hit."
)
# gpt-oss-20b ignores REPEAT_NOTE: on Nov 19 it asked for one test search nine times in a
# question, eight of them with the result in plain view. After MAX_IN_VIEW_REPEATS such
# repeats (re-fetches of shortened results do not count), the next request offers no
# tools and asks for the answer.
MAX_IN_VIEW_REPEATS = 3
REPEATS_PROMPT = (
    "You keep asking for results you already have. Answer now with what you know, without "
    "calling tools, and say what you could not confirm."
)
REPEATS_NOTE = ("(Stopped early: the model kept asking for results it already had, so it was "
                "asked to answer with what it had found.)")


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
    quotes: list[QuoteCheck] = field(default_factory=list)
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    limit_hit: bool = False
    trajectory_path: Path | None = None

    @property
    def invalid_citations(self) -> list[CitationCheck]:
        return [c for c in self.citations if not c.valid]

    @property
    def unfound_quotes(self) -> list[QuoteCheck]:
        """Quoted code whose names are not in the files cited beside it."""
        return [q for q in self.quotes if q.missing]


def check_citations(text: str, tools: ToolSet) -> list[CitationCheck]:
    """Validate every citation in `text`: right snapshot, a file of it, lines inside it.

    "Inside" means within the file's module span, so a line past the end of the file is
    reported rather than silently accepted; a range is inside when both ends are.
    Invalid citations are returned, never dropped. A bare `path:line` counts when the
    path is a file of the snapshot or holds a `/`, so a version (`v1.2:3`) or a host and
    port is not taken for one.
    """
    store, snapshot_id = tools.context.store, tools.context.snapshot_id
    checks: list[CitationCheck] = []
    seen: set[str] = set()
    for match in citation_pattern(snapshot_id).finditer(text):
        if match.group(0) in seen:
            continue
        seen.add(match.group(0))
        check = _check(match, snapshot_id, store)
        if check is not None:
            checks.append(check)
    return checks


def _check(match: re.Match[str], snapshot_id: str, store: Any) -> CitationCheck | None:
    """One citation found by `citation_pattern`, checked; None when it is not one."""
    citation, full = match.group(0), match.group("full") is not None
    g = "f" if full else "b"
    path, name = match.group(g + "path"), match.group(g + "name")
    line, end = match.group(g + "line"), match.group(g + "end")
    if full and not citation.startswith(snapshot_id + ":"):
        return CitationCheck(citation, "", int(line or 0), False,
                             f"not from snapshot {snapshot_id}")
    module = store.module_for_path(snapshot_id, path)
    if module is None and not full and "/" not in path:
        return None  # a version or a host name, not a place in this snapshot
    if module is None:
        return CitationCheck(citation, path, int(line or 0), False, "no such file")
    if name is not None:  # a key: the place is where the symbol starts
        return _check_key(citation, path, name, snapshot_id, store)
    if line is None:
        return CitationCheck(citation, path, 0, False, "no line number")
    first = int(line)
    last = int(end) if end else first
    if last < first:
        return CitationCheck(citation, path, first, False, "the range ends before it starts")
    span = module.span
    if not (span.start_line <= first and last <= span.end_line):
        return CitationCheck(citation, path, first, False,
                             f"line outside the file (1-{span.end_line})")
    return CitationCheck(citation, path, first, True)


def _check_key(citation: str, path: str, name: str, snapshot_id: str,
               store: Any) -> CitationCheck:
    """A cited key: valid at the symbol's first line when it names one symbol of the file.

    The model often drops the class (`race_replay.py::_compute_lap_times` for the method
    `F1RaceReplayWindow._compute_lap_times`, four times in one answer on Nov 19), so a
    name that is not a whole qualname counts when exactly one symbol's qualname ends in it.
    """
    found = store.nodes_by_key(f"{path}::{name}", snapshot_id)
    if not found:
        found = [n for n in store.nodes_in_file(snapshot_id, path)
                 if n.qualname.endswith("." + name)]
    if len(found) == 1:
        return CitationCheck(citation, path, found[0].span.start_line, True)
    reason = f"{len(found)} symbols end with that name" if found else "no such symbol"
    return CitationCheck(citation, path, 0, False, reason)


def citation_pattern(snapshot_id: str) -> re.Pattern[str]:
    """Citations in an answer: this snapshot's, anything else shaped like one, bare paths.

    A repository name can hold a space ("Antidote graph-hacks"), which the general shape
    does not allow, so this snapshot's own id is matched as written. A citation of
    another snapshot is still found, and then reported as not from this one. Group
    `full` is set for the contract's shape (its line and range are optional here, so a
    file cited without a line is reported); otherwise the match is a bare path. Either
    can end in `::qualname` instead of a line: a key.
    """
    snapshot = f"(?:{re.escape(snapshot_id)}|" + r"[\w.\-]+@[0-9a-f]{12})"
    full = (f"(?P<full>{snapshot}:(?P<fpath>{_PATH})"
            + r"(?:::(?P<fname>" + _NAME + r")|:(?P<fline>\d+)" + _RANGE.format("fend")
            + r")?)")
    return re.compile(f"{full}|{_BARE}")


def ask(
    question: str,
    store: Any,
    snapshot_id: str,
    client: LLMClient,
    max_steps: int = 20,
    data_dir: str | Path | None = None,
    config: Config | None = None,
    on_step: OnStep | None = None,
    history: Sequence[Exchange] = (),
) -> Answer:
    """Answer `question` about one snapshot; write a trajectory file; check citations.

    `history` is the earlier exchanges of the same chat, as `recent_exchanges` chose them;
    they are sent as context before the question, and recorded in the trajectory (D-64).
    """
    config = config or Config()
    tools = ToolSet(store, snapshot_id, config)
    snapshot = tools.context.snapshot
    history = list(history)
    # The symbols the question names, or failing that an earlier question, found before step 1.
    leads = look_up(question, tools, [e.question for e in history])
    messages = [
        Message("system", system_prompt(store, snapshot, tools.specs)),
        Message("user", with_history(question + leads_text(leads), history)),
    ]
    first: dict[str, Any] = {"question": question}  # what step 1's record also holds
    if history:
        first["history"] = [{"question": e.question, "answer": e.answer} for e in history]
    if leads:
        first["leads"] = [_lead_record(lead) for lead in leads]
    answer = Answer(text="")
    log: list[dict[str, Any]] = []
    try:
        _run(messages, tools, client, max_steps, answer, log, on_step or _no_step, first)
        answer.citations = check_citations(answer.text, tools)
        answer.quotes = check_quotes(answer.text, answer.citations, tools,
                                     citation_pattern(snapshot_id))
        if log:
            log[-1]["invalid_citations"] = [c.text for c in answer.invalid_citations]
            log[-1]["unfound_quotes"] = [q.text for q in answer.unfound_quotes]
    finally:
        answer.trajectory_path = _write_trajectory(
            Path(data_dir if data_dir is not None else config.data_dir), log)
    return answer


def _lead_record(lead: dict[str, Any]) -> dict[str, Any]:
    """A lead as the trajectory keeps it: its keys, not the whole symbols."""
    record = {"name": lead["name"], "keys": [s["key"] for s in lead["symbols"]],
              "more": lead["more"]}
    if lead.get("earlier"):
        record["earlier"] = True
    return record


def _no_step(record: dict[str, Any]) -> None:
    """The default: nobody is watching."""


def _run(messages: list[Message], tools: ToolSet, client: LLMClient, max_steps: int,
         answer: Answer, log: list[dict[str, Any]], on_step: OnStep,
         first: dict[str, Any]) -> None:
    made: dict[str, tuple[int, str]] = {}  # each call so far -> (step shown whole, result)
    in_view_repeats = 0
    for step in range(1, max_steps + 1):
        response, seconds = _timed_chat(client, _for_model(messages), tools.specs)
        answer.steps = step
        answer.input_tokens += response.input_tokens
        answer.output_tokens += response.output_tokens
        messages.append(Message("assistant", response.text, tool_calls=response.tool_calls))
        record = _step_record(step, response, seconds)
        if step == 1:
            record.update(first)
        log.append(record)
        if not response.tool_calls:
            answer.text = response.text
            record["final"] = True
            on_step(record)
            return
        for call in response.tool_calls:
            result, repeat_of, in_view = _result_of(call, step, tools, made)
            in_view_repeats += in_view
            messages.append(Message("tool", result, tool_call_id=call.id))
            # The result itself is kept (at most MAX_RESULT_CHARS), so a recorded answer
            # can be replayed step by step and a wrong answer traced to what it was shown.
            entry = {"name": call.name, "arguments": call.arguments,
                     "result_chars": len(result), "result": result}
            if repeat_of is not None:
                entry["repeat_of"] = repeat_of
            record["tool_calls"].append(entry)
        on_step(record)
        if in_view_repeats >= MAX_IN_VIEW_REPEATS:
            _finish(messages, client, answer, log, REPEATS_PROMPT, REPEATS_NOTE,
                    stopped="repeats")
            on_step(log[-1])
            return
    answer.limit_hit = True
    _finish(messages, client, answer, log, LIMIT_PROMPT, LIMIT_NOTE.format(n=max_steps),
            limit_hit=True)
    on_step(log[-1])


def _result_of(call: ToolCall, step: int, tools: ToolSet,
               made: dict[str, tuple[int, str]]) -> tuple[str, int | None, bool]:
    """The call's result; for a repeat (see REPEAT_NOTE) the step it repeats; and whether
    it was a repeat of a result the model can still see whole."""
    identity = json.dumps([call.name, call.arguments], sort_keys=True)
    if identity not in made:
        result = tools.call_json(call.name, call.arguments)
        made[identity] = (step, result)
        return result, None, False
    shown_at, result = made[identity]
    note = REPEAT_NOTE.format(step=shown_at)
    # The next request shows the results of the last FULL_RESULT_STEPS steps whole.
    if _shortened(result) is None or step - shown_at < FULL_RESULT_STEPS:
        return json.dumps({"note": note}), shown_at, True
    made[identity] = (step, result)
    data = _json(result)
    if isinstance(data, dict):  # still JSON, so it can be shortened to its places later
        return json.dumps({**data, "note": note}, ensure_ascii=False), shown_at, False
    return f"{result}\n[{note}]", shown_at, False


def _finish(messages: list[Message], client: LLMClient, answer: Answer,
            log: list[dict[str, Any]], prompt: str, note: str, **marks: Any) -> None:
    """One last call without tools, so the user gets what is known and is told why."""
    messages.append(Message("user", prompt))
    response, seconds = _timed_chat(client, _for_model(messages), None)
    answer.steps += 1
    answer.input_tokens += response.input_tokens
    answer.output_tokens += response.output_tokens
    answer.text = f"{response.text}\n\n{note}".strip()
    record = _step_record(answer.steps, response, seconds)
    record.update({"final": True, **marks})
    log.append(record)


def _for_model(messages: list[Message]) -> list[Message]:
    """The conversation as sent: tool results older than the last steps shortened."""
    turns = [i for i, m in enumerate(messages) if m.role == "assistant"]
    if len(turns) <= FULL_RESULT_STEPS:
        return messages
    keep_from = turns[-FULL_RESULT_STEPS]
    sent = []
    for i, message in enumerate(messages):
        if i < keep_from and message.role == "tool":
            short = _shortened(message.content)
            if short is not None:
                message = replace(message, content=short)
        sent.append(message)
    return sent


def _shortened(content: str) -> str | None:
    """An old tool result as the model is sent it, or None to send it whole.

    It keeps every place the result named, as `qualname citation`, plus what was asked
    and whether there was more; signatures, source and text go. The first version kept
    the first 400 characters: on Nov 19 that hid `build_gold`, the third of nine
    callers, and the answer said nothing else called the function. Replayed on six real
    trajectories, keeping the places sent from 28% fewer to 3% more characters. A result
    that names no places keeps its first characters. Nothing is shortened into something
    longer than itself.
    """
    if len(content) <= OLD_RESULT_CHARS:
        return None
    data = _json(content)
    places = _places(data)
    if places:
        kept = {k: data[k] for k in KEPT_FIELDS if isinstance(data, dict) and k in data}
        short = json.dumps({**kept, "places": places,
                            "note": PLACES_NOTE.format(n=len(content))}, ensure_ascii=False)
    else:
        short = content[:OLD_RESULT_CHARS] + SHORTENED_NOTE.format(n=len(content))
    return short if len(short) < len(content) else None


def _json(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def _places(value: Any, found: list[str] | None = None) -> list[str]:
    """`qualname citation` of everything in a result that carries a citation, in order."""
    found = [] if found is None else found
    if isinstance(value, dict):
        citation = value.get("citation")
        if isinstance(citation, str):
            key = str(value.get("key") or "")
            name = key.split("::", 1)[1] if "::" in key else str(value.get("name") or "")
            place = f"{name} {citation}".strip()
            if place not in found:
                found.append(place)
        for item in value.values():
            _places(item, found)
    elif isinstance(value, list):
        for item in value:
            _places(item, found)
    return found


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
