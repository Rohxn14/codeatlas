"""Retry, fallback, caching and the usage log, through `LLMClient.chat`."""

import json
import random

import pytest

from codeatlas.llm.cache import LLMCache
from codeatlas.llm.client import LLMClient
from codeatlas.llm.errors import CacheMissError, LLMRequestError, LLMUnavailableError
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


def make_client(providers, tmp_path, mode="read_write", sleeps=None):
    cache = LLMCache(tmp_path / "llm_cache.sqlite")
    return LLMClient(
        providers,
        cache=cache,
        cache_mode=mode,
        usage_log=tmp_path / "llm_usage.jsonl",
        sleep=(sleeps.append if sleeps is not None else lambda _s: None),
        rng=random.Random(0),
    )


def test_429_then_success_backs_off(script, tmp_path):
    s = script([(429, load("groq_rate_limit.json")), (200, load("groq_text.json"))],
               models=load("groq_models.json"))
    sleeps: list[float] = []
    reply = make_client([groq(s)], tmp_path, sleeps=sleeps).chat(msgs())
    assert reply.text == "ok" and reply.provider == "groq"
    assert len(s.chat_requests) == 2
    assert len(sleeps) == 1 and 1.0 <= sleeps[0] < 2.0


def test_backoff_grows_exponentially(tmp_path):
    client = make_client([], tmp_path)
    delays = [client._backoff(n) for n in range(3)]
    assert [int(d) for d in delays] == [1, 2, 4]


def test_groq_5xx_falls_back_to_gemini(script, tmp_path):
    g = script([(503, load("groq_server_error.json"))] * 3, models=load("groq_models.json"))
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


def test_gone_model_switches_to_newest_of_family(script, tmp_path):
    s = script([(200, load("groq_text.json"))], models=load("groq_models.json"))
    provider = GroqProvider("openai/gpt-oss-10b", api_key="t", http_client=s.client())
    make_client([provider], tmp_path).chat(msgs())
    assert provider.model == "openai/gpt-oss-120b"
    assert s.chat_requests[0]["body"]["model"] == "openai/gpt-oss-120b"
    assert s.model_requests == 1
