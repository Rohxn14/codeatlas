"""What every provider adapter offers, and the shared model-fallback rule."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
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


def retry_after_seconds(headers: Mapping[str, str] | None, text: str) -> float | None:
    """How long a rate-limited provider asked us to wait, or None if it did not say.

    Groq sends a `retry-after` header in seconds and writes "try again in 7.66s" (or
    "1m2.5s") in its message; Gemini writes `retryDelay: "34s"` or "retry in 34.5s".
    """
    if headers is not None:
        try:
            seconds = float(headers.get("retry-after", ""))
        except ValueError:
            seconds = -1.0
        if seconds >= 0:
            return seconds
    match = _WAIT_IN_TEXT.search(text)
    if match is None:
        return None
    units = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}
    return sum(float(n) * units[u] for n, u in _DURATION_PART.findall(match.group(1)))


_DURATION = r"(?:\d+(?:\.\d+)?(?:h|ms|m|s))+"
_WAIT_IN_TEXT = re.compile(
    rf"(?:try again in|retry in|retryDelay['\"]?\s*:\s*['\"]?)\s*({_DURATION})", re.IGNORECASE)
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(h|ms|m|s)")


def model_family(model_id: str) -> str:
    """A model's name with every version number blanked: `gemini-3.8-flash` -> `gemini-#-flash`.

    A size such as `20b` stays as written (decision D-17): `gpt-oss-20b` and
    `gpt-oss-120b` are different families, since a bigger model has different limits
    and cost. Suffixes such as `-lite` or `-preview` also make a different family.
    """
    return _VERSION.sub("#", model_id)


# A number, unless it is a size: digits followed by "b" and then the end or a non-letter.
_VERSION = re.compile(r"(?<![\d.])\d+(?:\.\d+)*(?![\d.]|[bB](?![a-zA-Z]))")


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
        listed = ", ".join(sorted(m.id for m in available)[:20])
        log.warning("%s: model %s is not listed and has no same-family match; keeping it. "
                    "Listed: %s", provider.name, provider.model, listed)
    elif chosen != provider.model:
        log.warning("%s: model %s is gone; switching to %s", provider.name, provider.model,
                    chosen)
        provider.model = chosen
