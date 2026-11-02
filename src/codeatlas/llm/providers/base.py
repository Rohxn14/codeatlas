"""What every provider adapter offers, and the shared model-fallback rule."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from codeatlas.llm.types import LLMResponse, Message, ToolSpec

log = logging.getLogger(__name__)

# Sent when no key is in the environment: the cloud proxy replaces the auth header, and
# both SDKs refuse to start without some key. A real failure surfaces as a 401 later.
PLACEHOLDER_KEY = "attached-by-proxy"


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """One entry of a provider's model list; `created` is a Unix time when known."""

    id: str
    created: int | None = None


class Provider(Protocol):
    """One LLM provider. Adapters raise only `codeatlas.llm.errors` exceptions."""

    name: str
    model: str

    def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None,
        temperature: float,
        max_tokens: int | None,
    ) -> LLMResponse: ...

    def list_models(self) -> list[ModelInfo]: ...


def model_family(model_id: str) -> str:
    """A model's name with every version number blanked: `gemini-3.8-flash` -> `gemini-#-flash`.

    Sizes count as numbers too, so `gpt-oss-20b` and `gpt-oss-120b` are one family;
    suffixes such as `-lite` or `-preview` make a different family.
    """
    return re.sub(r"\d+(?:\.\d+)*", "#", model_id)


def _version(model_id: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", model_id))


def choose_model(configured: str, available: Sequence[ModelInfo]) -> str | None:
    """The configured model if it is listed, else the newest of its family, else None.

    Newest means the latest `created` time when the provider gives one (Groq does),
    then the highest version numbers (Gemini lists no dates).
    """
    if any(m.id == configured for m in available):
        return configured
    family = model_family(configured)
    same = [m for m in available if model_family(m.id) == family]
    if not same:
        return None
    return max(same, key=lambda m: (m.created or 0, _version(m.id))).id


def resolve_model(provider: Provider) -> None:
    """Swap `provider.model` for a listed one when the configured model is gone.

    A failed listing keeps the configured model: the chat call will report the real error.
    """
    try:
        available = provider.list_models()
    except Exception as exc:  # listing is best effort
        log.warning("%s: could not list models (%s); keeping %s", provider.name, exc,
                    provider.model)
        return
    chosen = choose_model(provider.model, available)
    if chosen is None:
        log.warning("%s: model %s is not listed and has no family match; keeping it",
                    provider.name, provider.model)
    elif chosen != provider.model:
        log.warning("%s: model %s is gone; switching to %s", provider.name, provider.model,
                    chosen)
        provider.model = chosen
