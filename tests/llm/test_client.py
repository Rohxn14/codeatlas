"""Retry, fallback, caching and the usage log, through `LLMClient.chat`."""

import json
import random
from dataclasses import replace

import pytest

from codeatlas.llm.cache import LLMCache, cache_key
from codeatlas.llm.client import LLMClient
from codeatlas.llm.errors import CacheMissError, LLMRequestError, LLMUnavailableError
from codeatlas.llm.providers.base import ModelInfo
from codeatlas.llm.providers.gemini import GeminiProvider
from codeatlas.llm.providers.groq import GroqProvider
from codeatlas.llm.types import Message

from .conftest import load


def msgs():
    return [Message("user", "hi")]


def groq(s):
    return GroqProvider("openai/gpt-oss-20b", api_key="t", http_client=s.client())


def gemini(s):
    return GeminiProvider("gemini-3.8-flash", api_key="t", http_client=s.client())


class Clock:
    """A fake clock that the client's sleep moves forward, so tests never really wait."""

    def __init__(self, sleeps=None):
        self.now = 0.0
        self.sleeps = sleeps if sleeps is not None else []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(providers, tmp_path, mode="read_write", sleeps=None, clock=None):
    cache = LLMCache(tmp_path / "llm_cache.sqlite")
    clock = clock or Clock(sleeps)
    return LLMClient(
        providers,
        cache=cache,
        cache_mode=mode,
        usage_log=tmp_path / "llm_usage.jsonl",
        sleep=clock.sleep,
        clock=clock,
        rng=random.Random(0),
    )


def test_a_429_rests_the_provider_then_the_client_waits_for_it(script, tmp_path):
    s = script([(429, load("groq_rate_limit.json")), (200, load("groq_text.json"))],
               models=load("groq_models.json"))
    sleeps: list[float] = []
    client = make_client([groq(s)], tmp_path, sleeps=sleeps)
    waits = []
    client.on_wait = lambda seconds, label: waits.append((seconds, label))
    reply = client.chat(msgs())
    assert reply.text == "ok" and reply.provider == "groq"
    assert len(s.chat_requests) == 2
    assert sleeps == [60.0]  # no hint from the provider: rest a full minute, not 1-2 s
    assert waits == [(60.0, "groq openai/gpt-oss-20b")]


def test_a_429_moves_straight_to_the_next_provider_and_stays_resting(script, tmp_path):
    g = script([(429, load("groq_rate_limit.json"), {"retry-after": "7"}),
                (200, load("groq_text.json"))], models=load("groq_models.json"))
    m = script([(200, load("gemini_text.json"))] * 2, models=load("gemini_models.json"))
    clock = Clock()
    client = make_client([groq(g), gemini(m)], tmp_path, clock=clock)
    assert client.chat(msgs()).provider == "gemini"
    assert clock.sleeps == []  # no retry and no wait: Gemini was free
    # Within Groq's 7 s rest, the next request skips it without asking.
    assert client.chat([Message("user", "again")]).provider == "gemini"
    assert len(g.chat_requests) == 1
    clock.now += 7
    assert client.chat([Message("user", "later")]).provider == "groq"


def test_a_wait_longer_than_the_limit_fails_and_says_why(script, tmp_path):
    g = script([(429, load("groq_rate_limit.json"), {"retry-after": "3600"})],
               models=load("groq_models.json"))
    sleeps: list[float] = []
    with pytest.raises(LLMUnavailableError, match="free again in 3600 s"):
        make_client([groq(g)], tmp_path, sleeps=sleeps).chat(msgs())
    assert sleeps == []


def test_the_wait_is_read_from_the_message_when_there_is_no_header(script, tmp_path):
    limited = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                         "message": "Quota exceeded. Please retry in 34.5s."}}
    m = script([(429, limited), (200, load("gemini_text.json"))],
               models=load("gemini_models.json"))
    sleeps: list[float] = []
    assert make_client([gemini(m)], tmp_path, sleeps=sleeps).chat(msgs()).provider == "gemini"
    assert sleeps == [34.5]


def test_two_models_of_one_provider_rest_separately(script, tmp_path):
    small = script([(429, load("groq_rate_limit.json"))], models=load("groq_models.json"))
    large = script([(200, load("groq_text.json"))], models=load("groq_models.json"))
    bigger = GroqProvider("openai/gpt-oss-120b", api_key="t", http_client=large.client())
    reply = make_client([groq(small), bigger], tmp_path).chat(msgs())
    assert reply.text == "ok" and len(large.chat_requests) == 1


def test_backoff_grows_exponentially(tmp_path):
    client = make_client([], tmp_path)
    delays = [client._backoff(n) for n in range(3)]
    assert [int(d) for d in delays] == [1, 2, 4]


def test_groq_5xx_falls_back_to_gemini(script, tmp_path):
    # A 500 is retried: it can be a one-off. (A 503 or 504 rests instead, below.)
    g = script([(500, load("groq_server_error.json"))] * 3, models=load("groq_models.json"))
    m = script([(200, load("gemini_text.json"))], models=load("gemini_models.json"))
    sleeps: list[float] = []
    reply = make_client([groq(g), gemini(m)], tmp_path, sleeps=sleeps).chat(msgs())
    assert reply.provider == "gemini" and reply.text == "ok"
    assert len(g.chat_requests) == 3  # max 3 tries on Groq
    assert len(sleeps) == 2  # no sleep after the last try before falling back


def test_400_is_raised_without_fallback(script, tmp_path):
    g = script([(400, load("groq_bad_request.json"))], models=load("groq_models.json"))
    m = script([(200, load("gemini_text.json"))], models=load("gemini_models.json"))
    with pytest.raises(LLMRequestError):
        make_client([groq(g), gemini(m)], tmp_path).chat(msgs())
    assert m.chat_requests == []


def test_all_providers_failing(script, tmp_path):
    g = script([(503, load("groq_server_error.json"))] * 3, models=load("groq_models.json"))
    m = script([(429, load("gemini_rate_limit.json"))] * 3, models=load("gemini_models.json"))
    with pytest.raises(LLMUnavailableError):
        make_client([groq(g), gemini(m)], tmp_path).chat(msgs())


def test_read_write_records_then_replays(script, tmp_path):
    s = script([(200, load("groq_text.json"))], models=load("groq_models.json"))
    client = make_client([groq(s)], tmp_path)
    first = client.chat(msgs())
    second = client.chat(msgs())
    assert (first.cached, second.cached) == (False, True)
    assert second.text == first.text and second.provider == "groq"
    assert len(s.chat_requests) == 1
    usage = (tmp_path / "llm_usage.jsonl").read_text().splitlines()
    assert len(usage) == 1  # cached answers are free and not logged
    record = json.loads(usage[0])
    assert record["provider"] == "groq" and record["input_tokens"] == 12
    assert "latency_ms" in record


def test_replay_only_hits_and_misses(script, tmp_path):
    s = script([(200, load("groq_text.json"))], models=load("groq_models.json"))
    make_client([groq(s)], tmp_path).chat(msgs())
    replay = make_client([groq(s)], tmp_path, mode="replay_only")
    assert replay.chat(msgs()).cached is True
    with pytest.raises(CacheMissError):
        replay.chat(msgs(), temperature=0.5)
    assert len(s.chat_requests) == 1


def test_off_never_caches(script, tmp_path):
    s = script([(200, load("groq_text.json"))] * 2, models=load("groq_models.json"))
    client = make_client([groq(s)], tmp_path, mode="off")
    assert not client.chat(msgs()).cached
    assert not client.chat(msgs()).cached
    assert len(s.chat_requests) == 2


def test_namespace_separates_cache_entries(script, tmp_path):
    s = script([(200, load("groq_text.json"))] * 2, models=load("groq_models.json"))
    a = make_client([groq(s)], tmp_path)
    b = make_client([groq(s)], tmp_path)
    b.namespace = "eval-run-2"
    a.chat(msgs())
    assert b.chat(msgs()).cached is False


def test_gone_model_never_switches_to_another_size(script, tmp_path):
    """D-17: a retired gpt-oss-10b must not silently become gpt-oss-120b."""
    s = script([(200, load("groq_text.json"))], models=load("groq_models.json"))
    provider = GroqProvider("openai/gpt-oss-10b", api_key="t", http_client=s.client())
    make_client([provider], tmp_path).chat(msgs())
    assert provider.model == "openai/gpt-oss-10b"
    assert s.chat_requests[0]["body"]["model"] == "openai/gpt-oss-10b"
    assert s.model_requests == 1


def test_empty_answer_falls_back_and_is_never_cached(script, tmp_path):
    m = script([(200, load("gemini_max_tokens.json"))], models=load("gemini_models.json"))
    g = script([(200, load("groq_text.json"))] * 2, models=load("groq_models.json"))
    client = make_client([gemini(m), groq(g)], tmp_path)
    reply = client.chat(msgs())
    assert reply.provider == "groq" and reply.text == "ok"
    assert len(m.chat_requests) == 1  # an empty answer is not retried on the same provider


def test_only_empty_answers_make_the_call_fail(script, tmp_path):
    m = script([(200, load("gemini_max_tokens.json"))], models=load("gemini_models.json"))
    g = script([(200, load("groq_max_tokens.json"))], models=load("groq_models.json"))
    client = make_client([gemini(m), groq(g)], tmp_path)
    with pytest.raises(LLMUnavailableError, match="empty answer"):
        client.chat(msgs())
    assert client.cache.get_chat(cache_key(msgs(), None, 0.0, None, "default")) is None


def test_replay_only_without_a_cache_is_refused():
    with pytest.raises(ValueError, match="replay_only"):
        LLMClient([], cache=None, cache_mode="replay_only")


def test_tool_call_replays_exactly(script, tmp_path):
    s = script([(200, load("gemini_tool_call.json"))], models=load("gemini_models.json"))
    client = make_client([gemini(s)], tmp_path)
    first = client.chat(msgs())
    second = client.chat(msgs())
    assert replace(first, cached=True) == second  # id, arguments and signature included
    assert len(s.chat_requests) == 1


def test_retired_model_is_resolved_again_after_a_404(script, tmp_path):
    s = script([(404, {"error": {"code": 404, "message": "model not found",
                                 "status": "NOT_FOUND"}}),
                (200, load("gemini_text.json"))])
    provider = gemini(s)
    listings = iter([[ModelInfo("gemini-3.8-flash")], [ModelInfo("gemini-3.9-flash")]])
    provider.list_models = lambda: next(listings)
    reply = make_client([provider], tmp_path).chat(msgs())
    assert reply.text == "ok" and provider.model == "gemini-3.9-flash"
    assert s.chat_requests[1]["path"].endswith("/models/gemini-3.9-flash:generateContent")


LIMITS = {"x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-tokens": "100",
          "x-ratelimit-reset-tokens": "30s", "x-ratelimit-limit-requests": "1000",
          "x-ratelimit-remaining-requests": "999", "x-ratelimit-reset-requests": "1m26.4s"}


def test_a_request_too_big_for_the_minute_left_skips_that_model(script, tmp_path):
    g = script([(200, load("groq_text.json"), LIMITS), (200, load("groq_text.json"))],
               models=load("groq_models.json"))
    m = script([(200, load("gemini_text.json"))], models=load("gemini_models.json"))
    clock = Clock()
    client = make_client([groq(g), gemini(m)], tmp_path, clock=clock)
    assert client.chat(msgs()).provider == "groq"  # Groq says: 100 tokens left for 30 s
    big = [Message("user", "x" * 800)]  # about 200 tokens
    assert client.chat(big).provider == "gemini"
    assert len(g.chat_requests) == 1  # Groq was not asked: it would have said 429
    clock.now += 30
    assert client.chat([Message("user", "y" * 800)]).provider == "groq"


def test_the_usage_log_keeps_the_limits_and_the_estimate(script, tmp_path):
    g = script([(200, load("groq_text.json"), LIMITS)], models=load("groq_models.json"))
    make_client([groq(g)], tmp_path).chat([Message("user", "z" * 400)])
    line = json.loads((tmp_path / "llm_usage.jsonl").read_text(encoding="utf-8"))
    assert line["estimated_input_tokens"] == 100
    assert line["limits"] == {"limit_tokens": 8000.0, "remaining_tokens": 100.0,
                              "reset_tokens": 30.0, "limit_requests": 1000.0,
                              "remaining_requests": 999.0, "reset_requests": 86.4}


def test_a_provider_whose_rest_ends_during_the_pass_is_tried_again(script, tmp_path):
    # Seen on Nov 19: Groq rested, Gemini's retries took longer than Groq's rest, and the
    # request failed although Groq was free again.
    g = script([(429, load("groq_rate_limit.json"), {"retry-after": "2"}),
                (200, load("groq_text.json"))], models=load("groq_models.json"))
    m = script([(500, load("groq_server_error.json"))] * 3, models=load("gemini_models.json"))
    clock = Clock()
    reply = make_client([groq(g), gemini(m)], tmp_path, clock=clock).chat(msgs())
    assert reply.provider == "groq" and len(g.chat_requests) == 2
    assert clock.now > 2  # Gemini's backoff outlasted Groq's rest: no extra wait needed


def test_a_zero_second_retry_hint_still_rests_a_second(script, tmp_path):
    g = script([(429, load("groq_rate_limit.json"), {"retry-after": "0"}),
                (200, load("groq_text.json"))], models=load("groq_models.json"))
    sleeps: list[float] = []
    assert make_client([groq(g)], tmp_path, sleeps=sleeps).chat(msgs()).text == "ok"
    assert sleeps == [1.0]


OVERLOADED = {
    503: {"error": {"code": 503, "status": "UNAVAILABLE", "message": "This model is currently "
                    "experiencing high demand. Please try again later."}},
    504: {"error": {"code": 504, "status": "DEADLINE_EXCEEDED",
                    "message": "Deadline expired before operation could complete."}},
}


@pytest.mark.parametrize("status", [503, 504])
def test_an_overloaded_provider_rests_instead_of_being_retried(script, tmp_path, status):
    # Seen all day on Nov 19: Gemini's three tries per request cost about a minute.
    m = script([(status, OVERLOADED[status]), (200, load("gemini_text.json"))],
               models=load("gemini_models.json"))
    g = script([(200, load("groq_text.json"))] * 2, models=load("groq_models.json"))
    clock = Clock()
    client = make_client([gemini(m), groq(g)], tmp_path, clock=clock)
    assert client.chat(msgs()).provider == "groq"
    assert len(m.chat_requests) == 1 and clock.sleeps == []  # no retry, no backoff
    assert client.chat([Message("user", "again")]).provider == "groq"
    assert len(m.chat_requests) == 1  # still resting: not asked
    clock.now += 60
    assert client.chat([Message("user", "later")]).provider == "gemini"
