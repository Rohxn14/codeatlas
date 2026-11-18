"""Gemini adapter against mocked HTTP: conversion both ways and error classification."""

import base64

import pytest

from codeatlas.llm.errors import LLMEmptyResponseError, LLMRequestError, LLMTransientError
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
    assert (call.name, call.arguments) == ("search_code", {"query": "parse_args", "limit": 5})
    assert call.id.startswith("call_") and len(call.id) == len("call_") + 12
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


def test_made_up_tool_call_ids_differ_across_turns(script):
    s = script([(200, load("gemini_tool_call.json"))] * 2)
    p = provider(s)
    first = p.chat([Message("user", "find it")], [SEARCH], 0.0, None).tool_calls[0]
    second = p.chat([Message("user", "find it")], [SEARCH], 0.0, None).tool_calls[0]
    assert first.id != second.id
    history = [
        Message("user", "find"),
        Message("assistant", "", tool_calls=(ToolCall(first.id, "search_code", {}),)),
        Message("tool", "r1", tool_call_id=first.id),
        Message("assistant", "", tool_calls=(ToolCall(second.id, "read_file", {}),)),
        Message("tool", "r2", tool_call_id=second.id),
    ]
    _, contents = to_gemini_contents(history)
    names = [part.function_response.name for c in contents for part in c.parts
             if part.function_response is not None]
    assert names == ["search_code", "read_file"]


def test_thinking_level_is_sent_and_can_be_turned_off(script):
    s = script([(200, load("gemini_text.json"))] * 2)
    GeminiProvider("gemini-3.8-flash", api_key="t", http_client=s.client(),
                   thinking_level="minimal").chat([Message("user", "hi")], None, 0.0, None)
    GeminiProvider("gemini-3.8-flash", api_key="t", http_client=s.client(),
                   thinking_level="").chat([Message("user", "hi")], None, 0.0, None)
    configs = [r["body"]["generationConfig"] for r in s.chat_requests]
    # The SDK sends the inner key in snake case; the API accepts either spelling.
    assert configs[0]["thinkingConfig"] == {"thinking_level": "MINIMAL"}
    assert "thinkingConfig" not in configs[1]


def test_max_tokens_answer_raises_empty_response(script):
    s = script([(200, load("gemini_max_tokens.json"))])
    with pytest.raises(LLMEmptyResponseError, match="MAX_TOKENS"):
        provider(s).chat([Message("user", "hi")], None, 0.0, 10)


def test_a_429_carries_the_retry_delay_from_its_details(script):
    body = {"error": {"code": 429, "message": "You exceeded your current quota.",
                      "status": "RESOURCE_EXHAUSTED",
                      "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo",
                                   "retryDelay": "21s"}]}}
    s = script([(429, body)])
    provider = GeminiProvider("gemini-3.8-flash", api_key="t", http_client=s.client())
    with pytest.raises(LLMTransientError) as caught:
        provider.chat([Message("user", "hi")], None, 0.0, None)
    assert caught.value.status == 429 and caught.value.retry_after == 21.0
