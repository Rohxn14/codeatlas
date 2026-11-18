"""Groq adapter: the OpenAI-compatible chat completions API, through the `groq` SDK."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from typing import Any

import groq
import httpx

from codeatlas.llm.errors import LLMEmptyResponseError, LLMRequestError, LLMTransientError
from codeatlas.llm.providers.base import (
    PLACEHOLDER_KEY,
    ModelInfo,
    rate_limits,
    retry_after_seconds,
)
from codeatlas.llm.types import LLMResponse, Message, ToolCall, ToolSpec


class GroqProvider:
    """Converts CodeAtlas messages to OpenAI-style dicts and back.

    The SDK's own retries are switched off: the client owns retry and fallback, so one
    policy covers every provider.
    """

    name = "groq"

    def __init__(
        self,
        model: str,
        timeout: float = 30.0,
        api_key: str | None = None,
        http_client: httpx.Client | None = None,
        reasoning_effort: str = "low",
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        # The `x-ratelimit-*` headers of the last answer (see `rate_limits`); the client
        # reads them to avoid sending a request this model's minute cannot fit.
        self.last_limits: dict[str, float] = {}
        self._client = groq.Groq(
            api_key=api_key or os.environ.get("GROQ_API_KEY") or PLACEHOLDER_KEY,
            timeout=timeout,
            max_retries=0,
            http_client=http_client,
        )

    def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None,
        temperature: float,
        max_tokens: int | None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [to_groq_message(m) for m in messages],
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = [to_groq_tool(t) for t in tools]
        if max_tokens is not None:
            kwargs["max_completion_tokens"] = max_tokens
        if self.reasoning_effort:  # gpt-oss models accept low, medium or high
            kwargs["reasoning_effort"] = self.reasoning_effort
        try:
            raw = self._client.chat.completions.with_raw_response.create(**kwargs)
            completion = raw.parse()
        except groq.APIError as exc:
            raise _translate(exc) from exc
        self.last_limits = rate_limits(raw.headers)
        return from_groq_completion(completion.model_dump(), self.model)

    def list_models(self) -> list[ModelInfo]:
        try:
            page = self._client.models.list()
        except groq.APIError as exc:
            raise _translate(exc) from exc
        return [ModelInfo(m.id, getattr(m, "created", None)) for m in page.data]


def to_groq_message(message: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.role == "tool":
        out["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        out["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in message.tool_calls
        ]
    return out


def to_groq_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def from_groq_completion(data: dict[str, Any], model: str) -> LLMResponse:
    """Read the first choice of a chat completion (as a plain dict)."""
    choice = data["choices"][0]
    message = choice["message"]
    calls = tuple(
        ToolCall(
            id=raw["id"],
            name=raw["function"]["name"],
            arguments=_parse_arguments(raw["function"].get("arguments")),
        )
        for raw in message.get("tool_calls") or ()
    )
    if not (message.get("content") or "") and not calls:
        raise LLMEmptyResponseError("groq", f"finish reason {choice.get('finish_reason')}")
    usage = data.get("usage") or {}
    return LLMResponse(
        text=message.get("content") or "",
        tool_calls=calls,
        provider="groq",
        model=data.get("model") or model,
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
    )


def _parse_arguments(raw: str | None) -> dict[str, Any]:
    """Tool arguments arrive as a JSON string; keep malformed text rather than drop it."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def _translate(exc: groq.APIError) -> Exception:
    if isinstance(exc, groq.APITimeoutError | groq.APIConnectionError):
        return LLMTransientError("groq", None, str(exc))
    status = getattr(exc, "status_code", None)
    if status == 429 or (status is not None and status >= 500):
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        return LLMTransientError("groq", status, str(exc),
                                 retry_after=retry_after_seconds(headers, str(exc)))
    return LLMRequestError("groq", status, str(exc))
