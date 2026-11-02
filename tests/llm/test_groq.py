"""Groq adapter against mocked HTTP: conversion both ways and error classification."""

import pytest

from codeatlas.llm.errors import LLMRequestError, LLMTransientError
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
