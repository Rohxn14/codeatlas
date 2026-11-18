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


class LLMUnavailableError(LLMError):
    """Every provider was tried and each one failed with a transient error."""


class CacheMissError(LLMError):
    """The cache is in `replay_only` mode and holds no answer for this request."""
