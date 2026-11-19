"""Errors the LLM layer raises, split by what the caller should do about them."""

from __future__ import annotations


class LLMError(Exception):
    """Base class for every error the LLM layer raises."""


class LLMRequestError(LLMError):
    """A 400-class error: the request itself is wrong, so another provider will not help."""

    def __init__(self, provider: str, status: int | None, message: str) -> None:
        super().__init__(f"{provider} rejected the request ({status}): {message}")
        self.provider = provider
        self.status = status


class LLMTransientError(LLMError):
    """A rate limit (429), server error (5xx) or timeout: worth retrying, then falling back.

    `retry_after` is how many seconds the provider asked us to wait, when it said so
    (a `retry-after` header, or "try again in 7.66s" in the message).
    """

    def __init__(
        self, provider: str, status: int | None, message: str, retry_after: float | None = None
    ) -> None:
        super().__init__(f"{provider} failed ({status or 'no status'}): {message}")
        self.provider = provider
        self.status = status
        self.retry_after = retry_after


class LLMEmptyResponseError(LLMError):
    """The provider answered with no text and no tool calls.

    This happens when thinking uses up the output budget (MAX_TOKENS), or a safety
    filter blocks the answer. An empty answer must never be cached, since replaying it
    would hide the failure for good; the client tries the next provider instead.
    """

    def __init__(self, provider: str, reason: str | None) -> None:
        super().__init__(f"{provider} returned an empty answer ({reason or 'no reason given'})")
        self.provider = provider
        self.reason = reason


class LLMBadToolCallError(LLMError):
    """The model's tool call failed the provider's own check, so there is no answer to use.

    Groq answers 400 `tool_use_failed` when gpt-oss calls a tool that was never offered
    (on Nov 19 it called `commentary`, the name of one of its own output channels) or
    writes arguments that are not JSON. The request was fine and another model may well
    manage it, so the client moves on, as for an empty answer, instead of failing the
    whole question the way a 400 does.
    """

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(f"{provider}: the model's tool call was rejected: {message}")
        self.provider = provider


class LLMUnavailableError(LLMError):
    """Every provider was tried and each one failed with a transient error."""


class CacheMissError(LLMError):
    """The cache is in `replay_only` mode and holds no answer for this request."""
