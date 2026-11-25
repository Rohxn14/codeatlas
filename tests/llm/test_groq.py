"""Groq adapter against mocked HTTP: conversion both ways and error classification."""

import pytest

from codeatlas.llm.errors import LLMEmptyResponseError, LLMRequestError, LLMTransientError
from codeatlas.llm.providers.base import retry_after_seconds
from codeatlas.llm.providers.groq import GroqProvider
from codeatlas.llm.types import Message, ToolCall, ToolSpec

from .conftest import load

SEARCH = ToolSpec(
    "search_code",
    "Search the code map",
    {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
)


def provider(script) -> GroqProvider:
    return GroqProvider("openai/gpt-oss-20b", api_key="test", http_client=script.client())


def test_text_reply(script):
    s = script([(200, load("groq_text.json"))])
    reply = provider(s).chat([Message("user", "hi")], None, 0.0, 50)
    assert reply.text == "ok"
    assert (reply.provider, reply.model) == ("groq", "openai/gpt-oss-20b")
    assert (reply.input_tokens, reply.output_tokens) == (12, 3)
    body = s.chat_requests[0]["body"]
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["max_completion_tokens"] == 50
    assert "tools" not in body


def test_tool_call_round_trip(script):
    s = script([(200, load("groq_tool_call.json"))])
    history = [
        Message("system", "You map code."),
        Message("user", "find it"),
        Message("assistant", "", tool_calls=(ToolCall("call_1", "search_code", {"query": "x"}),)),
        Message("tool", "[]", tool_call_id="call_1"),
    ]
    reply = provider(s).chat(history, [SEARCH], 0.0, None)
    assert reply.tool_calls == (
        ToolCall("call_abc", "search_code", {"query": "parse_args", "limit": 5}),
    )
    body = s.chat_requests[0]["body"]
    assert body["tools"][0]["function"]["name"] == "search_code"
    assert body["messages"][2]["tool_calls"][0]["function"]["arguments"] == '{"query": "x"}'
    assert body["messages"][3] == {"role": "tool", "content": "[]", "tool_call_id": "call_1"}


@pytest.mark.parametrize(
    ("status", "fixture", "error"),
    [
        (429, "groq_rate_limit.json", LLMTransientError),
        (503, "groq_server_error.json", LLMTransientError),
        (400, "groq_bad_request.json", LLMRequestError),
        (401, "groq_bad_request.json", LLMRequestError),
    ],
)
def test_errors_are_classified(script, status, fixture, error):
    s = script([(status, load(fixture))])
    with pytest.raises(error) as caught:
        provider(s).chat([Message("user", "hi")], None, 0.0, None)
    assert caught.value.status == status
    assert len(s.chat_requests) == 1  # the SDK's own retries are off


def test_malformed_arguments_are_kept():
    from codeatlas.llm.providers.groq import _parse_arguments

    assert _parse_arguments('{"a": 1') == {"_raw": '{"a": 1'}
    assert _parse_arguments("") == {}


def test_list_models(script):
    s = script([], models=load("groq_models.json"))
    ids = [m.id for m in provider(s).list_models()]
    assert "openai/gpt-oss-20b" in ids


def test_reasoning_effort_is_sent_and_can_be_turned_off(script):
    s = script([(200, load("groq_text.json"))] * 2)
    provider(s).chat([Message("user", "hi")], None, 0.0, None)
    GroqProvider("openai/gpt-oss-20b", api_key="t", http_client=s.client(),
                 reasoning_effort="").chat([Message("user", "hi")], None, 0.0, None)
    assert s.chat_requests[0]["body"]["reasoning_effort"] == "low"
    assert "reasoning_effort" not in s.chat_requests[1]["body"]


def test_length_cut_answer_raises_empty_response(script):
    s = script([(200, load("groq_max_tokens.json"))])
    with pytest.raises(LLMEmptyResponseError, match="length"):
        provider(s).chat([Message("user", "hi")], None, 0.0, 10)


@pytest.mark.parametrize(("headers", "text", "seconds"), [
    ({"retry-after": "12"}, "", 12.0),
    (None, "Rate limit reached. Please try again in 7.66s. Need more tokens?", 7.66),
    (None, "Please try again in 1m2.5s.", 62.5),
    (None, "Please try again in 250ms.", 0.25),
    ({"retry-after": "soon"}, "try again in 3s", 3.0),  # an unreadable header falls back
    (None, "Rate limit reached", None),
])
def test_the_wait_a_provider_asks_for_is_read(headers, text, seconds):
    assert retry_after_seconds(headers, text) == seconds


def test_a_429_carries_the_retry_after_header(script):
    s = script([(429, load("groq_rate_limit.json"), {"retry-after": "9"})])
    provider = GroqProvider("openai/gpt-oss-20b", api_key="t", http_client=s.client())
    with pytest.raises(LLMTransientError) as caught:
        provider.chat([Message("user", "hi")], None, 0.0, None)
    assert caught.value.retry_after == 9.0


def test_internal_markers_in_the_text_are_no_answer() -> None:
    # Nov 25: "...【assistant to=select_tests<|channel|>commentary <|constrain|>json..."
    from codeatlas.llm.errors import LLMBadOutputError
    from codeatlas.llm.providers.groq import from_groq_completion

    data = {"choices": [{"message": {"content": "It is <|channel|>commentary"}}]}
    with pytest.raises(LLMBadOutputError, match="internal markers"):
        from_groq_completion(data, "openai/gpt-oss-20b")
