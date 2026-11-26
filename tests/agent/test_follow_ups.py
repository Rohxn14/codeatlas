"""Follow-up questions: what is remembered, how it is sent, and how its subject is found (D-64)."""

import json

from codeatlas.agent.history import (
    CUT_MARK,
    HISTORY_INTRO,
    QUESTION_NOW,
    Exchange,
    recent_exchanges,
    with_history,
)
from codeatlas.agent.leads import EARLIER_MARK, look_up
from codeatlas.agent.loop import ask
from codeatlas.agent.tools import ToolSet

from .support import SNAP, make_client, reply


def chat(*numbers: int) -> list[Exchange]:
    return [Exchange(f"question {n}", f"answer {n}") for n in numbers]


# What is remembered


def test_the_last_three_are_remembered_oldest_first() -> None:
    assert recent_exchanges(chat(1, 2, 3, 4, 5)) == chat(3, 4, 5)
    assert recent_exchanges(chat(1, 2)) == chat(1, 2)
    assert recent_exchanges([]) == []


def test_limit_zero_remembers_nothing() -> None:
    # The trap: chat[-0:] is the whole list, not an empty one.
    assert recent_exchanges(chat(1, 2, 3), limit=0) == []


def test_a_question_with_no_answer_does_not_use_up_a_place() -> None:
    failed, running = Exchange("question 4", ""), Exchange("question 5", None)
    assert recent_exchanges([*chat(1, 2, 3), failed, running]) == chat(1, 2, 3)


def test_a_long_answer_is_cut_and_marked_and_a_question_never_is() -> None:
    (kept,) = recent_exchanges([Exchange("q" * 2000, "x" * 5000)])
    assert len(kept.answer) == 1200 and kept.answer.endswith(CUT_MARK)
    assert kept.question == "q" * 2000
    (exact,) = recent_exchanges([Exchange("q", "x" * 1200)])
    assert exact.answer == "x" * 1200  # exactly the limit is not cut


def test_the_chat_itself_is_not_changed() -> None:
    before = [Exchange("q", "x" * 5000), *chat(1, 2, 3)]
    copy = list(before)
    recent_exchanges(before, limit=2)
    assert before == copy


# How it is sent


def test_the_history_comes_before_the_question_and_says_it_is_not_evidence() -> None:
    assert with_history("Who calls it?", []) == "Who calls it?"
    sent = with_history("Who calls it?", chat(1, 2))
    assert sent.startswith(HISTORY_INTRO) and "not evidence" in HISTORY_INTRO
    assert "Question 1: question 1\nAnswer 1: answer 1\n\nQuestion 2: question 2" in sent
    assert sent.endswith(f"{QUESTION_NOW} Who calls it?")


def test_a_question_is_sent_with_its_history_and_the_trajectory_keeps_it(store, tmp_path):
    client, provider = make_client(reply("Only service.create."))
    history = [Exchange("What does Repo.save do?", "It stores a user.")]
    answer = ask("And who calls it?", store, SNAP, client, data_dir=tmp_path, history=history)
    sent = provider.requests[0][1].content
    assert sent.startswith(HISTORY_INTRO)
    assert "Question 1: What does Repo.save do?\nAnswer 1: It stores a user." in sent
    assert f"{QUESTION_NOW} And who calls it?" in sent
    first = json.loads(answer.trajectory_path.read_text(encoding="utf-8").splitlines()[0])
    assert first["question"] == "And who calls it?"  # as asked, without the history
    assert first["history"] == [{"question": "What does Repo.save do?",
                                 "answer": "It stores a user."}]


# How its subject is found


def test_a_follow_up_that_names_nothing_gets_the_leads_of_the_question_before(store, tmp_path):
    client, provider = make_client(reply("Only service.create."))
    answer = ask("And who calls it?", store, SNAP, client, data_dir=tmp_path,
                 history=[Exchange("What does Repo.save do?", "It stores a user.")])
    sent = provider.requests[0][1].content
    assert (f"- Repo.save: app/repo.py::Repo.save (function) {SNAP}:app/repo.py:2 "
            f"`def save(self, user)`{EARLIER_MARK}") in sent
    first = json.loads(answer.trajectory_path.read_text(encoding="utf-8").splitlines()[0])
    assert first["leads"] == [{"name": "Repo.save", "keys": ["app/repo.py::Repo.save"],
                               "more": 0, "earlier": True}]


def test_the_question_s_own_names_come_first_then_the_newest_earlier_question_that_names_one(
    store,
):
    tools = ToolSet(store, SNAP)
    leads = look_up("Does service.create call it?", tools, ["What does Repo.save do?"])
    assert [(lead["name"], lead.get("earlier", False)) for lead in leads] == [
        ("service.create", False), ("Repo.save", True)]
    # A chain of follow-ups: the newest earlier question names nothing, the one before does.
    leads = look_up("And what about tests?", tools,
                    ["What does Repo.save do?", "And who calls it?"])
    assert [lead["name"] for lead in leads] == ["Repo.save"]
    # Only the newest earlier question with a name counts, not every one.
    leads = look_up("Who calls it?", tools, ["What does Repo.save do?", "And service.create?"])
    assert [lead["name"] for lead in leads] == ["service.create"]
    # A name the question already has is not added twice.
    assert len(look_up("Who calls Repo.save?", tools, ["What is Repo.save?"])) == 1
