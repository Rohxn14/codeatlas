"""Gemini adapter: `generateContent` with function declarations, through `google-genai`.

Google now calls `generateContent` the legacy API and recommends the Interactions API;
the SDK's generate-content call is still documented, and keeping it behind this one
file means a later move touches nothing else.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Sequence
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

from codeatlas.llm.errors import LLMRequestError, LLMTransientError
from codeatlas.llm.providers.base import PLACEHOLDER_KEY, ModelInfo
from codeatlas.llm.types import LLMResponse, Message, ToolCall, ToolSpec

# Gemini 3 rejects a replayed function call without its thought signature. Calls that
# another provider made have none; Google documents this value for exactly that case.
SKIP_SIGNATURE = b"skip_thought_signature_validator"


class GeminiProvider:
    """Converts CodeAtlas messages to Gemini `Content` objects and back."""

    name = "gemini"

    def __init__(
        self,
        model: str,
        timeout: float = 60.0,
        api_key: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self._client = genai.Client(
            api_key=api_key or os.environ.get("GEMINI_API_KEY") or PLACEHOLDER_KEY,
            http_options=types.HttpOptions(timeout=int(timeout * 1000), httpx_client=http_client),
        )

    def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None,
        temperature: float,
        max_tokens: int | None,
    ) -> LLMResponse:
        system, contents = to_gemini_contents(messages)
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
            tools=[to_gemini_tool(tools)] if tools else None,
        )
        try:
            response = self._client.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except (errors.APIError, httpx.TransportError) as exc:
            raise _translate(exc) from exc
        return from_gemini_response(response, self.model)

    def list_models(self) -> list[ModelInfo]:
        try:
            models = list(self._client.models.list(config={"page_size": 1000}))
        except (errors.APIError, httpx.TransportError) as exc:
            raise _translate(exc) from exc
        return [
            ModelInfo(m.name.removeprefix("models/"))
            for m in models
            if m.name and "generateContent" in (m.supported_actions or ["generateContent"])
        ]


def to_gemini_contents(messages: Sequence[Message]) -> tuple[str | None, list[types.Content]]:
    """System text goes to `system_instruction`; tool results become function responses.

    Consecutive turns of the same role are merged, because Gemini expects all answers
    to one set of parallel calls in a single `user` turn.
    """
    names = {c.id: c.name for m in messages for c in m.tool_calls}
    system = "\n\n".join(m.content for m in messages if m.role == "system") or None
    contents: list[types.Content] = []
    for message in messages:
        if message.role == "system":
            continue
        role = "model" if message.role == "assistant" else "user"
        parts = _parts(message, names)
        if contents and contents[-1].role == role:
            contents[-1].parts = [*(contents[-1].parts or []), *parts]
        else:
            contents.append(types.Content(role=role, parts=parts))
    return system, contents


def _parts(message: Message, names: dict[str, str]) -> list[types.Part]:
    if message.role == "tool":
        call_id = message.tool_call_id or ""
        response = types.FunctionResponse(
            id=call_id or None,
            name=names.get(call_id, call_id),
            response={"result": message.content},
        )
        return [types.Part(function_response=response)]
    parts = [types.Part(text=message.content)] if message.content else []
    for call in message.tool_calls:
        signature = base64.b64decode(call.signature) if call.signature else SKIP_SIGNATURE
        parts.append(
            types.Part(
                function_call=types.FunctionCall(id=call.id, name=call.name, args=call.arguments),
                thought_signature=signature,
            )
        )
    return parts


def to_gemini_tool(tools: Sequence[ToolSpec]) -> types.Tool:
    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=t.name, description=t.description, parameters_json_schema=t.parameters
            )
            for t in tools
        ]
    )


def from_gemini_response(response: types.GenerateContentResponse, model: str) -> LLMResponse:
    """Collect visible text and function calls from the first candidate; skip thoughts."""
    texts: list[str] = []
    calls: list[ToolCall] = []
    candidate = (response.candidates or [None])[0]
    parts = (candidate.content.parts if candidate and candidate.content else None) or []
    for part in parts:
        if part.function_call is not None:
            fc = part.function_call
            signature = part.thought_signature
            calls.append(
                ToolCall(
                    id=fc.id or f"call_{len(calls)}",
                    name=fc.name or "",
                    arguments=dict(fc.args or {}),
                    signature=base64.b64encode(signature).decode("ascii") if signature else None,
                )
            )
        elif part.text and not part.thought:
            texts.append(part.text)
    usage = response.usage_metadata
    return LLMResponse(
        text="".join(texts),
        tool_calls=tuple(calls),
        provider="gemini",
        model=response.model_version or model,
        input_tokens=(usage.prompt_token_count or 0) if usage else 0,
        output_tokens=_output_tokens(usage),
    )


def _output_tokens(usage: types.GenerateContentResponseUsageMetadata | None) -> int:
    """Thinking tokens are billed as output, so they are counted here too."""
    if usage is None:
        return 0
    return (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)


def _translate(exc: Any) -> Exception:
    if isinstance(exc, httpx.TransportError):  # timeouts and dropped connections
        return LLMTransientError("gemini", None, f"{type(exc).__name__}: {exc}")
    status = getattr(exc, "code", None)
    if status == 429 or (isinstance(status, int) and status >= 500):
        return LLMTransientError("gemini", status, str(exc))
    return LLMRequestError("gemini", status, str(exc))
