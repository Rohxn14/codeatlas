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
    # The result itself is kept, so the step can be replayed and checked later.
    assert len(tool["result"]) == tool["result_chars"] and "app/repo.py" in tool["result"]
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


def test_each_step_is_reported_as_it_finishes(store, tmp_path):
    client, _ = make_client(
        reply(calls=[call("1", "get_file_symbols", path="app/repo.py")]),
        reply("done"),
    )
    seen = []
    answer = ask("q", store, SNAP, client, data_dir=tmp_path,
                 on_step=lambda record: seen.append(dict(record)))
    assert [r["step"] for r in seen] == [1, 2] and answer.steps == 2
    assert seen[0]["tool_calls"][0]["name"] == "get_file_symbols"
    assert seen[1]["final"] is True


def test_a_snapshot_id_with_a_space_is_cited_whole():
    from codeatlas.agent.loop import citation_pattern

    sid = "Antidote graph-hacks@0ba557abfca8"
    text = f"See ({sid}:src/a.py:3), and other@0ba557abfca8:b.py:9."
    found = [m.group(0) for m in citation_pattern(sid).finditer(text)]
    assert found == [f"{sid}:src/a.py:3", "other@0ba557abfca8:b.py:9"]


def test_old_tool_results_are_cut_short_for_the_model_only() -> None:
    from codeatlas.agent.loop import OLD_RESULT_CHARS, _for_model
    from codeatlas.llm import Message

    long = "x" * 1000
    messages = [Message("system", "s"), Message("user", "q")]
    for n in range(1, 4):  # three steps, each with one long tool result
        messages += [Message("assistant", "", tool_calls=(call(str(n), "t"),)),
                     Message("tool", long, tool_call_id=str(n))]
    sent = _for_model(messages)
    assert sent[3].content.startswith("x" * OLD_RESULT_CHARS)
    assert sent[3].content.endswith("[older result shortened from 1000 characters; "
                                    "call the tool again to see all of it]")
    assert sent[5].content == long and sent[7].content == long  # the last two steps whole
    assert messages[3].content == long  # the conversation itself (and so the trajectory) keeps it
    assert _for_model(messages[:6]) == messages[:6]  # two steps: nothing to cut


def test_the_model_is_sent_the_shortened_conversation(store, tmp_path):
    client, provider = make_client(
        reply(calls=[call("1", "search_symbols", name="create")]),
        reply(calls=[call("2", "search_symbols", name="save")]),
        reply(calls=[call("3", "search_symbols", name="rename")]),
        reply("Done."),
    )
    ask("what is here?", store, SNAP, client, data_dir=tmp_path)
    last = provider.requests[3]
    assert [m.role for m in last].count("tool") == 3
    assert last[5].content == provider.requests[2][5].content  # step 2 still whole at step 4


def test_a_repeated_call_is_not_run_again_and_points_at_the_result_in_view(
    store, tmp_path, monkeypatch,
):
    runs = []
    original = ToolSet.call_json

    def counted(self, name, args=None):
        runs.append(name)
        return original(self, name, args)

    monkeypatch.setattr(ToolSet, "call_json", counted)
    client, provider = make_client(
        reply(calls=[call("1", "get_file_symbols", path="app/service.py")]),
        reply(calls=[call("2", "get_file_symbols", path="app/service.py")]),
        reply("Done."),
    )
    answer = ask("q", store, SNAP, client, data_dir=tmp_path)
    assert runs == ["get_file_symbols"]  # the repeat was answered without running the tool
    sent = provider.requests[2]
    assert len(sent[3].content) > 400 and "app/service.py::create" in sent[3].content  # whole
    assert json.loads(sent[5].content) == {
        "note": "Same tool and arguments as step 1: the result has not changed. "
                "Work from that result, or answer."}
    steps = read_lines(answer.trajectory_path)
    assert "repeat_of" not in steps[0]["tool_calls"][0]
    assert steps[1]["tool_calls"][0]["repeat_of"] == 1


def test_a_repeat_of_a_result_cut_short_gets_it_whole_again(store, tmp_path):
    long = call("1", "get_file_symbols", path="app/service.py")  # 559 characters: cut later
    short = call("2", "search_symbols", name="save")  # 269 characters: never cut
    client, provider = make_client(
        reply(calls=[long, short]),
        reply(calls=[call("3", "search_symbols", name="create")]),
        reply(calls=[call("4", "search_symbols", name="rename")]),
        reply(calls=[call("5", "get_file_symbols", path="app/service.py"),
                     call("6", "search_symbols", name="save")]),
        reply("Done."),
    )
    answer = ask("q", store, SNAP, client, data_dir=tmp_path)
    sent = provider.requests[4]
    first, again = sent[3].content, sent[-2].content
    assert "older result shortened from 559 characters" in first  # step 1, as the model sees it
    whole = json.loads(provider.requests[1][3].content)  # step 1's result, as first sent
    assert json.loads(again) == {**whole, "note": "Same tool and arguments as step 1: the "
                                 "result has not changed. Work from that result, or answer."}
    assert json.loads(sent[-1].content)["note"].startswith("Same tool and arguments as step 1")
    repeats = [c.get("repeat_of") for c in read_lines(answer.trajectory_path)[3]["tool_calls"]]
    assert repeats == [1, 1]


def callers_result(n: int) -> str:
    """A find_callers result like the real one of Nov 19: n callers, long signatures."""
    results = [{"key": f"src/pipeline/m{i}.py::build_{i}", "kind": "function",
                "name": f"build_{i}", "path": f"src/pipeline/m{i}.py", "line": 10 * i,
                "citation": f"{SNAP}:src/pipeline/m{i}.py:{10 * i}",
                "signature": f"def build_{i}(year: int, round_number: int, *, root: str = "
                             "lake.DEFAULT_LAKE_ROOT, telemetry: bool = False)",
                "confidence": 1.0} for i in range(1, n + 1)]
    return json.dumps({"symbol": {"key": "src/pipeline/contracts.py::validate",
                                  "citation": f"{SNAP}:src/pipeline/contracts.py:158"},
                       "direction": "callers", "depth": 2, "total": 38, "truncated": True,
                       "results": results})


def test_an_old_result_keeps_every_place_it_named() -> None:
    from codeatlas.agent.loop import _for_model
    from codeatlas.llm import Message

    result = callers_result(9)
    messages = [Message("system", "s"), Message("user", "q"),
                Message("assistant", "", tool_calls=(call("1", "find_callers"),)),
                Message("tool", result, tool_call_id="1")]
    for n in (2, 3):
        messages += [Message("assistant", "", tool_calls=(call(str(n), "t"),)),
                     Message("tool", "{}", tool_call_id=str(n))]
    sent = json.loads(_for_model(messages)[3].content)
    # The first version kept 400 characters: callers 3 to 9 were gone (Nov 19).
    assert f"build_9 {SNAP}:src/pipeline/m9.py:90" in sent["places"]
    assert sent["places"][0] == f"validate {SNAP}:src/pipeline/contracts.py:158"
    assert len(sent["places"]) == 10 and "signature" not in json.dumps(sent)
    assert (sent["direction"], sent["total"], sent["truncated"]) == ("callers", 38, True)
    assert sent["note"] == f"older result shortened from {len(result)} characters to the " \
                           "places it named"
    assert len(json.dumps(sent)) < len(result) / 2


def test_a_result_is_never_shortened_into_something_longer() -> None:
    from codeatlas.agent.loop import _shortened

    long_query = json.dumps({"query": "q" * 450, "citation": f"{SNAP}:a.py:1"})
    assert _shortened(long_query) is None  # the kept query alone is longer: sent whole
    assert _shortened("x" * 401) is None  # 400 characters plus the note would be longer
    assert _shortened("x" * 1000).startswith("x" * 400)  # no places: the first characters


def test_the_system_prompt_names_the_tools_without_repeating_their_specs(store):
    from codeatlas.agent.prompts import system_prompt

    tools = ToolSet(store, SNAP)
    prompt = system_prompt(store, tools.context.snapshot, tools.specs)
    assert all(spec.name in prompt for spec in tools.specs)
    assert not any(spec.description in prompt for spec in tools.specs)  # sent in the specs


NB_HYPHEN = chr(0x2011)  # how gpt-oss-120b writes a range: 588‑600
OPEN, CLOSE = chr(0x3010), chr(0x3011)  # the brackets it puts around a citation


def test_every_shape_of_citation_in_an_answer_is_checked(store):
    # All seen on Nov 19: a bare path, a range with a non-breaking hyphen, a file with no
    # line, a key. Before, none of them was found, so none was checked.
    tools = ToolSet(store, SNAP)
    text = (f"Bare: {OPEN}app/repo.py:2{CLOSE} and app/ghost.py:1. "
            f"Range: {SNAP}:app/service.py:3{NB_HYPHEN}4, too long "
            f"{SNAP}:app/service.py:6-99, backwards {SNAP}:app/repo.py:4-2. "
            f"No line: `{SNAP}:app/repo.py`. Keys: {OPEN}app/service.py::create{CLOSE}, "
            f"{SNAP}:app/repo.py::Repo.save, app/repo.py::save (no class) and "
            "app/service.py::missing. "
            "Not citations: v1.2:3, example.com:8080, 12:30, notes.md::x.")
    checks = {c.text: (c.line, c.valid, c.reason) for c in check_citations(text, tools)}
    assert checks == {
        "app/repo.py:2": (2, True, ""),
        "app/ghost.py:1": (1, False, "no such file"),
        f"{SNAP}:app/service.py:3{NB_HYPHEN}4": (3, True, ""),
        f"{SNAP}:app/service.py:6-99": (6, False, "line outside the file (1-7)"),
        f"{SNAP}:app/repo.py:4-2": (4, False, "the range ends before it starts"),
        f"{SNAP}:app/repo.py": (0, False, "no line number"),
        "app/service.py::create": (3, True, ""),  # where the symbol starts
        f"{SNAP}:app/repo.py::Repo.save": (2, True, ""),
        "app/repo.py::save": (2, True, ""),  # the one symbol of the file ending in .save
        "app/service.py::missing": (0, False, "no such symbol"),
    }
