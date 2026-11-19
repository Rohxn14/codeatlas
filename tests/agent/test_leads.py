"""Code-like names in a question, looked up before the model's first step (B3)."""

import json

import pytest

from codeatlas.agent.leads import LEADS_INTRO, code_names, leads_text, look_up
from codeatlas.agent.loop import ask
from codeatlas.agent.tools import ToolSet
from codeatlas.llm import ToolCall

from .support import SNAP, make_client, reply


@pytest.mark.parametrize(("question", "names"), [
    ("Which tests cover classify_pit_passage?", ["classify_pit_passage"]),
    ("Which parts call contracts.validate, and for which tables?", ["contracts.validate"]),
    ("Where is `UserService` used, and createUser?", ["UserService", "createUser"]),
    ("How does the replay work? Explain the complete pipeline.", []),  # plain words only
    ("What does main.py do, e.g. at startup?", []),  # a file name and an abbreviation
    ("a_b, c_d, e_f and g_h", ["a_b", "c_d", "e_f"]),  # at most three
    ("Is Repo.save like repo.save?", ["Repo.save"]),  # case does not make a new name
])
def test_code_names(question, names):
    assert code_names(question) == names


def test_only_exact_matches_are_leads(store):
    tools = ToolSet(store, SNAP)
    leads = look_up("Who calls service.create, and what is cre_ate?", tools)
    assert [lead["name"] for lead in leads] == ["service.create"]  # cre_ate matches nothing
    assert [s["key"] for s in leads[0]["symbols"]] == ["app/service.py::create"]
    text = leads_text(leads)
    assert text.startswith("\n\n" + LEADS_INTRO)
    assert (f"- service.create: app/service.py::create (function) {SNAP}:app/service.py:3 "
            "`def create(user)`") in text


def test_the_question_is_sent_with_its_leads_and_recorded_without_them(store, tmp_path):
    client, provider = make_client(
        reply(calls=[ToolCall("1", "find_callers", {"key": "app/repo.py::Repo.save"})]),
        reply("Done."),
    )
    question = "What calls Repo.save?"
    answer = ask(question, store, SNAP, client, data_dir=tmp_path)
    sent = provider.requests[0][1].content
    assert sent.startswith(question + "\n\n" + LEADS_INTRO)
    assert f"- Repo.save: app/repo.py::Repo.save (function) {SNAP}:app/repo.py:2" in sent
    first = json.loads(answer.trajectory_path.read_text(encoding="utf-8").splitlines()[0])
    assert first["question"] == question
    assert first["leads"] == [{"name": "Repo.save", "keys": ["app/repo.py::Repo.save"],
                               "more": 0}]


def test_a_plain_question_is_sent_as_it_is(store, tmp_path):
    client, provider = make_client(reply("Nothing to look up."))
    ask("How does saving work?", store, SNAP, client, data_dir=tmp_path)
    assert provider.requests[0][1].content == "How does saving work?"
