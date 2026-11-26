"""Asking from the web app: the question box, the answer page, and who may ask.

The language model is scripted: no test calls a real provider or needs a key.
"""

import re
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from codeatlas.config import Config
from codeatlas.indexer.pipeline.index import index_repository
from codeatlas.llm import LLMClient, LLMResponse, LLMUnavailableError, ToolCall
from codeatlas.web import create_app, snapshot_slug
from codeatlas.web.app import LLM_KEYS

FILES = {
    "lib/util.py": "def helper():\n    pass\n",
    "README.md": "# Demo\n\n## Install\nRun the zeppelin installer.\n",
}


class Scripted:
    """A provider that answers with the next scripted reply, or raises it."""

    name = "scripted"
    model = "scripted-1"

    def __init__(self, replies: Sequence[LLMResponse | Exception]) -> None:
        self.replies = list(replies)

    def chat(self, messages: Any, tools: Any, temperature: float, max_tokens: Any) -> LLMResponse:
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def list_models(self) -> list:
        return []


def reply(text: str = "", calls: Sequence[ToolCall] = ()) -> LLMResponse:
    return LLMResponse(text, tuple(calls), "scripted", "scripted-1", 100, 20)


@pytest.fixture
def indexed(make_repo: Callable[..., Path], tmp_path: Path) -> tuple[Path, Config, str]:
    config = Config(data_dir=(tmp_path / "data").as_posix())
    db_path = tmp_path / "data" / "codeatlas.db"
    sid = index_repository(str(make_repo(FILES, name="demo")), config, db_path).snapshot["id"]
    return db_path, config, sid


def app_with(indexed: tuple[Path, Config, str], *replies: LLMResponse | Exception,
             **options: Any) -> tuple[TestClient, str]:
    db_path, config, sid = indexed
    client = LLMClient([Scripted(replies)], cache_mode="off", max_tries=1)
    app = create_app(db_path, config, llm=lambda: client, **options)
    return TestClient(app, follow_redirects=False), f"/s/{snapshot_slug(sid)}"


def finish(client: TestClient, location: str) -> str:
    page = None
    for _ in range(600):
        page = client.get(location)
        assert page.status_code == 200
        if 'http-equiv="refresh"' not in page.text:
            return page.text
        threading.Event().wait(0.05)
    # This test failed about once in nine full runs: say what the page last showed.
    raise AssertionError(f"not answered within 30 s; the page said: {main_text(page.text)}")


def main_text(html: str) -> str:
    """The page's main content as plain text, for an assertion message."""
    body = html.split("<main", 1)[-1]
    return " ".join(re.sub(r"<[^>]+>", " ", body).split())[:1500]


def ask(client: TestClient, base: str, question: str) -> str:
    started = client.post(f"{base}/ask", data={"question": question})
    assert started.status_code == 303, started.text
    return started.headers["location"]


def test_a_question_is_answered_with_its_steps_and_checked_citations(
    indexed: tuple[Path, Config, str],
) -> None:
    sid = indexed[2]
    client, base = app_with(
        indexed,
        reply(calls=[ToolCall("1", "search_docs", {"query": "install"})]),
        reply(f"Run the installer ({sid}:README.md:3); `helper` is at {sid}:lib/util.py:1. "
              f"Not here: {sid}:lib/gone.py:4. <script>x</script>"),
    )
    assert "Ask about" in client.get(f"{base}/ask").text
    location = ask(client, base, "How do I install this?")
    assert location.startswith(f"{base}/ask/")
    page = finish(client, location)

    assert "No answer." not in page, main_text(page)  # the run itself failed: say why
    assert "How do I install this?" in page
    assert f'href="{base}/file?path=README.md#L3"' in page, main_text(page)
    assert f'href="{base}/file?path=lib/util.py#L1"' in page
    assert "not a real place: no such file" in page
    assert "1 of 3 citations point at no real place" in page
    assert "&lt;script&gt;x&lt;/script&gt;" in page and "<script>x" not in page
    assert "<code>search_docs</code>" in page and "query=&#39;install&#39;" in page
    assert "2 model calls, 200 tokens in, 40 out" in page
    # The question is listed on the Ask page for this snapshot.
    assert location in client.get(f"{base}/ask").text


def test_a_repeated_tool_call_is_shown_as_the_same_as_its_first_step(
    indexed: tuple[Path, Config, str],
) -> None:
    client, base = app_with(
        indexed,
        reply(calls=[ToolCall("1", "search_docs", {"query": "install"})]),
        reply(calls=[ToolCall("2", "search_docs", {"query": "install"})]),
        reply("Run the installer."),
    )
    page = finish(client, ask(client, base, "How do I install this?"))
    assert page.count("query=&#39;install&#39;") == 2
    assert "same as step 1" in page, main_text(page)


def test_an_answer_with_no_citations_says_nothing_was_checked(
    indexed: tuple[Path, Config, str],
) -> None:
    client, base = app_with(indexed, reply("It is probably fine."))
    page = finish(client, ask(client, base, "Is it fine?"))
    assert "cites nothing, so none of it was checked" in page
    assert "answered without looking anything up" in page


def test_a_model_that_cannot_be_reached_gives_a_failed_answer(
    indexed: tuple[Path, Config, str],
) -> None:
    client, base = app_with(indexed, LLMUnavailableError("rate limited"))
    page = finish(client, ask(client, base, "Anything?"))
    assert "No answer." in page and "could not be reached" in page and "rate limited" in page


def test_an_empty_or_long_question_comes_back_to_the_form(
    indexed: tuple[Path, Config, str],
) -> None:
    client, base = app_with(indexed)
    empty = client.post(f"{base}/ask", data={"question": "   "})
    assert empty.status_code == 400 and "Type a question first." in empty.text
    long = client.post(f"{base}/ask", data={"question": "x" * 2001})
    assert long.status_code == 400 and "at most 2,000 characters" in long.text
    assert "Asked here" not in client.get(f"{base}/ask").text


def test_without_a_key_the_page_says_how_to_set_one(
    indexed: tuple[Path, Config, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in LLM_KEYS:
        monkeypatch.delenv(name, raising=False)
    db_path, config, sid = indexed
    client = TestClient(create_app(db_path, config), follow_redirects=False)
    base = f"/s/{snapshot_slug(sid)}"
    page = client.get(f"{base}/ask").text
    assert "No language model key is set" in page and "<code>.env</code>" in page
    assert "$env:" not in page  # never ask anyone to type a key into a terminal
    refused = client.post(f"{base}/ask", data={"question": "hello"})
    assert refused.status_code == 400 and "Asked here" not in refused.text


def test_a_read_only_app_has_no_ask_tab_and_refuses_questions(
    indexed: tuple[Path, Config, str],
) -> None:
    client, base = app_with(indexed, read_only=True)
    assert f'href="{base}/ask"' not in client.get(f"{base}/").text
    assert client.get(f"{base}/ask").status_code == 403
    assert client.post(f"{base}/ask", data={"question": "hello"}).status_code == 403


def test_a_question_posted_from_another_website_is_refused(
    indexed: tuple[Path, Config, str],
) -> None:
    client, base = app_with(indexed)
    other = client.post(f"{base}/ask", data={"question": "hello"},
                        headers={"origin": "https://evil.example"})
    assert other.status_code == 403
    assert client.get(f"{base}/ask/0123456789ab").status_code == 404


def test_a_rate_limit_wait_is_shown_with_the_answer(indexed: tuple[Path, Config, str]) -> None:
    from codeatlas.llm.errors import LLMTransientError

    client, base = app_with(
        indexed,
        LLMTransientError("scripted", 429, "slow down", retry_after=0.2),
        reply("Nothing to cite."),
    )
    page = finish(client, ask(client, base, "Anything?"))
    assert "s waiting for rate limits)" in page
    assert "1 model call," in page  # the refused request is not counted as a step


def test_a_running_question_knows_it_is_waiting_for_a_rate_limit() -> None:
    from codeatlas.web.asks import Question

    question = Question("q1", "demo@0123456789ab", "Anything?", state="running")
    assert question.waiting_now is None
    question.record_wait(30.0, "groq openai/gpt-oss-20b")
    now = question.waiting_now
    assert now is not None and now["provider"] == "groq openai/gpt-oss-20b"
    # Windows' clock ticks every ~15 ms, so both readings can fall in one tick and
    # leave 30 plus float error (seen in CI: 30.00000000000003).
    assert now["left"] == pytest.approx(30, abs=1)
    question.state = "done"
    assert question.waiting_now is None and question.seconds_waited == 30.0


# The chat panel: the same questions, as a piece of a page.


def chat_until_done(client: TestClient, base: str) -> str:
    for _ in range(600):
        page = client.get(f"{base}/chat")
        assert page.status_code == 200
        if 'data-active="0"' in page.text:
            return page.text
        threading.Event().wait(0.05)
    raise AssertionError(f"still active after 30 s: {page.text[:800]}")


def test_the_chat_panel_asks_and_answers(indexed: tuple[Path, Config, str]) -> None:
    sid = indexed[2]
    client, base = app_with(
        indexed,
        reply(calls=[ToolCall("1", "search_docs", {"query": "install"})]),
        reply(f"**Run** the installer:\n\n- see {sid}:README.md:3\n- not {sid}:lib/gone.py:4"),
    )
    page = client.get(f"{base}/").text
    assert 'id="chat"' in page and f'data-url="{base}/chat"' in page and "/static/app.js" in page
    empty = client.get(f"{base}/chat").text
    assert 'id="chat-empty"' in empty and "<html" not in empty  # a piece, not a page
    started = client.post(f"{base}/chat", data={"question": "How do I <b>install</b> this?"})
    assert started.status_code == 200 and "&lt;b&gt;install" in started.text
    done = chat_until_done(client, base)
    assert "<strong>Run</strong> the installer" in done and "<li>" in done
    assert f'href="{base}/file?path=README.md#L3"' in done and ">README.md:3</a>" in done
    assert "not a real place: no such file" in done
    assert "1 of 2 citations point at no real place" in done
    assert "2 steps" in done and "search_docs(query=&#39;install&#39;)" in done
    assert "same as step" not in done


def test_the_chat_shows_why_a_question_was_not_started(indexed: tuple[Path, Config, str]) -> None:
    client, base = app_with(indexed)
    refused = client.post(f"{base}/chat", data={"question": "  "})
    assert refused.status_code == 400 and "Type a question first." in refused.text
    other = client.post(f"{base}/chat", data={"question": "hello"},
                        headers={"origin": "https://evil.example"})
    assert other.status_code == 403
    read_only, base = app_with(indexed, read_only=True)
    assert read_only.get(f"{base}/chat").status_code == 403
    assert 'id="chat"' not in read_only.get(f"{base}/").text


def test_a_question_can_be_stopped_between_steps(indexed: tuple[Path, Config, str]) -> None:
    db_path, config, sid = indexed
    asked, go = threading.Event(), threading.Event()

    class Slow(Scripted):
        def chat(self, *args: Any) -> LLMResponse:
            asked.set()
            assert go.wait(20)
            return super().chat(*args)

    calls = [reply(calls=[ToolCall(str(i), "search_docs", {"query": f"q{i}"})]) for i in range(9)]
    client = LLMClient([Slow(calls)], cache_mode="off", max_tries=1)
    app = create_app(db_path, config, llm=lambda: client)
    web, base = TestClient(app, follow_redirects=False), f"/s/{snapshot_slug(sid)}"
    web.post(f"{base}/chat", data={"question": "Go on for ever?"})
    assert asked.wait(20)
    page = web.get(f"{base}/chat").text
    qid = re.search(r'id="qa-([0-9a-f]+)"', page).group(1)  # type: ignore[union-attr]
    assert f'action="{base}/chat/{qid}/stop"' in page
    stopped = web.post(f"{base}/chat/{qid}/stop")
    assert stopped.status_code == 200 and "Stopping" in stopped.text
    go.set()
    done = chat_until_done(web, base)
    assert 'data-state="failed"' in done and "Stopped." in done
    assert web.post(f"{base}/chat/0123456789ab/stop").status_code == 404


def test_every_page_says_what_it_may_load(indexed: tuple[Path, Config, str]) -> None:
    client, base = app_with(indexed)
    for address in ("/", f"{base}/", f"{base}/chat", "/nothing-here"):
        policy = client.get(address).headers["content-security-policy"]
        assert "script-src 'self'" in policy and "default-src 'none'" in policy
        assert "unsafe" not in policy.split("script-src")[1].split(";")[0]


# Follow-up questions remember the ones before them (D-64).


def test_a_follow_up_is_sent_with_the_question_and_answer_before_it(
    indexed: tuple[Path, Config, str],
) -> None:
    from codeatlas.agent.history import HISTORY_INTRO

    sent: list[list[str]] = []

    class Recording(Scripted):
        def chat(self, messages: Any, *args: Any) -> LLMResponse:
            sent.append([m.content for m in messages])
            return super().chat(messages, *args)

    db_path, config, sid = indexed
    client = LLMClient([Recording([reply("Run the zeppelin installer."), reply("Nothing else.")])],
                       cache_mode="off", max_tries=1)
    web = TestClient(create_app(db_path, config, llm=lambda: client), follow_redirects=False)
    base = f"/s/{snapshot_slug(sid)}"
    web.post(f"{base}/chat", data={"question": "How do I install this?"})
    chat_until_done(web, base)
    web.post(f"{base}/chat", data={"question": "And what else does it need?"})
    done = chat_until_done(web, base)
    assert HISTORY_INTRO not in sent[0][1]  # the first question has nothing to remember
    follow = sent[1][1]
    assert follow.startswith(HISTORY_INTRO)
    assert "Question 1: How do I install this?\nAnswer 1: Run the zeppelin installer." in follow
    assert follow.endswith("The question now: And what else does it need?")
    assert "remembered 1 earlier question" in done


def test_a_question_remembers_only_answered_questions_about_the_same_snapshot() -> None:
    from codeatlas.agent.history import Exchange
    from codeatlas.agent.loop import Answer
    from codeatlas.web.asks import Questions

    seen: dict[str, list[Exchange]] = {}

    def work(snapshot_id: str, text: str, history: Any, on_step: Any, on_wait: Any) -> Answer:
        seen[text] = list(history)
        if text == "fails":
            raise RuntimeError("no model")
        return Answer(text=f"answer to {text}")

    questions = Questions(work)
    for snapshot, text in [("a@1", "one"), ("a@1", "fails"), ("b@2", "elsewhere"),
                           ("a@1", "two"), ("a@1", "three"), ("a@1", "four"), ("a@1", "five")]:
        questions.wait(questions.start(snapshot, text).id)
    assert seen["one"] == [] and seen["elsewhere"] == []
    assert seen["two"] == [Exchange("one", "answer to one")]  # the failed one is not there
    assert [e.question for e in seen["five"]] == ["two", "three", "four"]  # the last three


def test_the_chat_lists_questions_in_the_order_asked_even_within_one_clock_tick() -> None:
    from codeatlas.agent.loop import Answer
    from codeatlas.web.asks import Questions

    def work(*args: Any) -> Answer:
        return Answer(text="ok")

    questions = Questions(work)
    # Three (the most that may wait), started within a fraction of one 15.6 ms clock step.
    asked = [questions.start("a@1", f"question {n}").id for n in range(3)]
    for qid in asked:
        questions.wait(qid)
    assert [q.id for q in questions.recent("a@1")] == asked[::-1]
