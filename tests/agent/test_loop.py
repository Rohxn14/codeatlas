"""The agent loop with a scripted provider: tool steps, the step limit, citations, trajectory."""

import json

import pytest

from codeatlas.agent.loop import ask, check_citations
from codeatlas.agent.tools import ToolSet
from codeatlas.llm import ToolCall

from .support import SNAP, make_client, reply


def call(id_, tool, **args):
    return ToolCall(id_, tool, args)


def read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_two_step_tool_call_then_answer(store, tmp_path):
    good = f"{SNAP}:app/service.py:3"
    client, provider = make_client(
        reply(calls=[call("1", "search_symbols", name="create")], tokens=(100, 10)),
        reply(calls=[call("2", "find_callees", key="app/service.py::create")], tokens=(120, 12)),
        reply(f"`create` calls `Repo.save` ({good}).", tokens=(150, 20)),
    )
    answer = ask("what does create call?", store, SNAP, client, data_dir=tmp_path)
    assert answer.text.startswith("`create` calls")
    assert (answer.steps, answer.input_tokens, answer.output_tokens) == (3, 370, 42)
    assert answer.limit_hit is False and answer.invalid_citations == []
    assert [c.valid for c in answer.citations] == [True]
    # The model saw the system prompt (repo, tools, citation rule) and the tool results.
    first = provider.requests[0]
    assert first[0].role == "system" and SNAP in first[0].content
    assert "find_callers" in first[0].content and "repo@sha:path:line" in first[0].content
    last = provider.requests[2]
    assert [m.role for m in last] == ["system", "user", "assistant", "tool", "assistant", "tool"]
    assert last[3].tool_call_id == "1" and "app/service.py::create" in last[3].content
    assert "Repo.save" in last[5].content


def test_trajectory_has_one_line_per_step(store, tmp_path):
    client, _ = make_client(
        reply(calls=[call("1", "get_file_symbols", path="app/repo.py")]),
        reply("done"),
    )
    answer = ask("q", store, SNAP, client, data_dir=tmp_path)
    path = answer.trajectory_path
    assert path.parent == tmp_path / "trajectories" and path.suffix == ".jsonl"
    lines = read_lines(path)
    assert len(lines) == answer.steps == 2
    assert lines[0]["question"] == "q" and lines[0]["step"] == 1
    tool = lines[0]["tool_calls"][0]
    assert tool["name"] == "get_file_symbols" and tool["result_chars"] > 0
    assert lines[0]["input_tokens"] == 10 and "seconds" in lines[0]
    assert lines[1]["final"] is True and lines[1]["text"] == "done"


def test_step_limit_answers_with_what_is_known(store, tmp_path):
    loops = [reply(calls=[call(str(i), "search_symbols", name="save")]) for i in range(2)]
    client, provider = make_client(*loops, reply("Partial: save is in app/repo.py."))
    answer = ask("q", store, SNAP, client, max_steps=2, data_dir=tmp_path)
    assert answer.limit_hit is True and answer.steps == 3
    assert "Step limit of 2 reached" in answer.text and answer.text.startswith("Partial")
    # The closing call offers no tools and says why.
    assert "step limit" in provider.requests[2][-1].content.lower()
    lines = read_lines(answer.trajectory_path)
    assert len(lines) == 3 and lines[-1]["limit_hit"] is True


def test_invalid_citation_is_reported_not_dropped(store, tmp_path):
    text = (f"Real: {SNAP}:app/repo.py:2. Fake file: {SNAP}:app/ghost.py:1. "
            f"Past the end: {SNAP}:app/repo.py:99. "
            f"Other snapshot: demo@ffffffffffff:app/repo.py:1.")
    client, _ = make_client(reply(text))
    answer = ask("q", store, SNAP, client, data_dir=tmp_path)
    assert [c.valid for c in answer.citations] == [True, False, False, False]
    reasons = {c.text: c.reason for c in answer.invalid_citations}
    assert reasons[f"{SNAP}:app/ghost.py:1"] == "no such file"
    assert "outside the file (1-4)" in reasons[f"{SNAP}:app/repo.py:99"]
    assert "not from snapshot" in reasons["demo@ffffffffffff:app/repo.py:1"]
    assert answer.text == text  # the answer itself is untouched
    assert read_lines(answer.trajectory_path)[-1]["invalid_citations"] == [
        c.text for c in answer.invalid_citations]


def test_citation_parsing_ignores_punctuation_and_duplicates(store):
    tools = ToolSet(store, SNAP)
    text = f"See ({SNAP}:app/repo.py:2), also `{SNAP}:app/repo.py:2`. Then {SNAP}:app/service.py:7."
    checks = check_citations(text, tools)
    assert [(c.path, c.line, c.valid) for c in checks] == [("app/repo.py", 2, True),
                                                           ("app/service.py", 7, True)]


def test_trajectory_written_even_when_the_model_call_fails(store, tmp_path):
    client, _ = make_client(reply(calls=[call("1", "search_symbols", name="save")]))
    with pytest.raises(IndexError):
        ask("q", store, SNAP, client, data_dir=tmp_path)  # script runs out on step 2
    files = list((tmp_path / "trajectories").glob("*.jsonl"))
    assert len(files) == 1 and len(read_lines(files[0])) == 1


def test_unknown_tool_call_gets_an_error_result(store, tmp_path):
    client, provider = make_client(reply(calls=[call("1", "run_tests", path="x")]), reply("ok"))
    ask("q", store, SNAP, client, data_dir=tmp_path)
    assert "unknown tool" in provider.requests[1][-1].content
