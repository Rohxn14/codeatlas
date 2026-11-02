"""Gemini adapter against mocked HTTP: conversion both ways and error classification."""

import base64

import pytest

from codeatlas.llm.errors import LLMRequestError, LLMTransientError
from codeatlas.llm.providers.gemini import GeminiProvider, to_gemini_contents
from codeatlas.llm.types import Message, ToolCall, ToolSpec

from .conftest import load

SEARCH = ToolSpec(
    "search_code",
    "Search the code map",
    {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
)


def provider(script) -> GeminiProvider:
    return GeminiProvider("gemini-3.8-flash", api_key="test", http_client=script.client())


def test_text_reply_skips_thoughts(script):
    s = script([(200, load("gemini_text.json"))])
    reply = provider(s).chat([Message("system", "Be brief."), Message("user", "hi")], None, 0.0, 9)
    assert reply.text == "ok"
    assert (reply.provider, reply.model) == ("gemini", "gemini-3.8-flash")
    assert (reply.input_tokens, reply.output_tokens) == (10, 7)
    request = s.chat_requests[0]
    assert request["path"].endswith("/models/gemini-3.8-flash:generateContent")
    body = request["body"]
    assert body["systemInstruction"]["parts"][0]["text"] == "Be brief."
    assert body["contents"] == [{"role": "user", "parts": [{"text": "hi"}]}]
    assert body["generationConfig"]["maxOutputTokens"] == 9


def test_tool_call_and_signature(script):
    s = script([(200, load("gemini_tool_call.json"))])
    reply = provider(s).chat([Message("user", "find it")], [SEARCH], 0.0, None)
    (call,) = reply.tool_calls
    assert (call.id, call.name, call.arguments) == (
        "call_0", "search_code", {"query": "parse_args", "limit": 5},
    )
    assert base64.b64decode(call.signature) == b"sig-1"
    declaration = s.chat_requests[0]["body"]["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "search_code"
    # The SDK sends this key in snake case; the API accepts either spelling.
    assert declaration["parameters_json_schema"] == SEARCH.parameters


def test_history_conversion_merges_tool_results():
    signed = base64.b64encode(b"sig").decode()
    history = [
        Message("user", "find"),
        Message("assistant", "", tool_calls=(
            ToolCall("a", "search_code", {"query": "x"}, signature=signed),
            ToolCall("b", "read_file", {"path": "y"}),
        )),
        Message("tool", "r1", tool_call_id="a"),
        Message("tool", "r2", tool_call_id="b"),
    ]
    system, contents = to_gemini_contents(history)
    assert system is None
    assert [c.role for c in contents] == ["user", "model", "user"]
    calls = contents[1].parts
    assert calls[0].thought_signature == b"sig"
    assert calls[1].thought_signature == b"skip_thought_signature_validator"
    answers = contents[2].parts
    assert [p.function_response.name for p in answers] == ["search_code", "read_file"]
    assert answers[0].function_response.response == {"result": "r1"}


@pytest.mark.parametrize(
    ("status", "fixture", "error"),
    [
        (429, "gemini_rate_limit.json", LLMTransientError),
        (500, "gemini_rate_limit.json", LLMTransientError),
        (400, "gemini_bad_request.json", LLMRequestError),
    ],
)
def test_errors_are_classified(script, status, fixture, error):
    s = script([(status, load(fixture))])
    with pytest.raises(error) as caught:
        provider(s).chat([Message("user", "hi")], None, 0.0, None)
    assert caught.value.status == status
    assert len(s.chat_requests) == 1


def test_list_models_keeps_generate_content_only(script):
    s = script([], models=load("gemini_models.json"))
    ids = [m.id for m in provider(s).list_models()]
    assert "gemini-3.8-flash" in ids
    assert "text-embedding-005" not in ids
