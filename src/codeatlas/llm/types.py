"""Provider-independent request and response shapes.

The rest of CodeAtlas speaks only these types; each provider adapter converts them to
and from its own wire format, so switching or adding a provider touches one file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One function call the model asked for.

    `signature` carries Gemini's opaque thought signature, which Gemini 3 models require
    to see again when the call is sent back in a later turn. It is provider data, so it
    is left out of the cache key.
    """

    id: str
    name: str
    arguments: dict[str, Any]
    signature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolCall:
        return cls(data["id"], data["name"], dict(data["arguments"]), data.get("signature"))


@dataclass(frozen=True, slots=True)
class Message:
    """One turn of a conversation; `tool` messages answer the call named by `tool_call_id`."""

    role: Role
    content: str
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A function the model may call; `parameters` is a JSON schema object."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object"})


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """What a chat call returns, whichever provider (or the cache) answered it."""

    text: str
    tool_calls: tuple[ToolCall, ...]
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], cached: bool = False) -> LLMResponse:
        return cls(
            text=data["text"],
            tool_calls=tuple(ToolCall.from_dict(c) for c in data["tool_calls"]),
            provider=data["provider"],
            model=data["model"],
            input_tokens=int(data["input_tokens"]),
            output_tokens=int(data["output_tokens"]),
            cached=cached,
        )
