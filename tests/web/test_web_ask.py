"""Asking from the web app: the question box, the answer page, and who may ask.

The language model is scripted: no test calls a real provider or needs a key.
"""

import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from codeatlas.agent.loop import Answer, CitationCheck
from codeatlas.config import Config
from codeatlas.indexer.pipeline.index import index_repository
from codeatlas.llm import LLMClient, LLMResponse, LLMUnavailableError, ToolCall
from codeatlas.web import create_app, snapshot_slug
from codeatlas.web.app import LLM_KEYS
from codeatlas.web.asks import answer_parts

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
    for _ in range(600):
        page = client.get(location)
        assert page.status_code == 200
        if 'http-equiv="refresh"' not in page.text:
            return page.text
        threading.Event().wait(0.05)
    raise AssertionError("the question was not answered")


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

    assert "How do I install this?" in page
    assert f'href="{base}/file?path=README.md#L3"' in page
    assert f'href="{base}/file?path=lib/util.py#L1"' in page
    assert "not a real place: no such file" in page
    assert "1 of 3 citations point at no real place" in page
    assert "&lt;script&gt;x&lt;/script&gt;" in page and "<script>x" not in page
    assert "<code>search_docs</code>" in page and "query=&#39;install&#39;" in page
    assert "2 model calls, 200 tokens in, 40 out" in page
    # The question is listed on the Ask page for this snapshot.
    assert location in client.get(f"{base}/ask").text


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


def test_answer_parts_cut_the_text_at_each_citation() -> None:
    long, short = "r@0123456789ab:a.py:12", "r@0123456789ab:a.py:1"
    answer = Answer(f"see {long} and {short}.", citations=[
        CitationCheck(short, "a.py", 1, True), CitationCheck(long, "a.py", 12, False, "x")])
    parts = answer_parts(answer)
    assert [p.get("text") or p["cite"].line for p in parts] == ["see ", 12, " and ", 1, "."]


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
    assert 29 < now["left"] <= 30
    question.state = "done"
    assert question.waiting_now is None and question.seconds_waited == 30.0
