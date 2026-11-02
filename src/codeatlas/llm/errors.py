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
    """A rate limit (429), server error (5xx) or timeout: worth retrying, then falling back."""

    def __init__(self, provider: str, status: int | None, message: str) -> None:
        super().__init__(f"{provider} failed ({status or 'no status'}): {message}")
        self.provider = provider
        self.status = status


class LLMUnavailableError(LLMError):
    """Every provider was tried and each one failed with a transient error."""


class CacheMissError(LLMError):
    """The cache is in `replay_only` mode and holds no answer for this request."""
