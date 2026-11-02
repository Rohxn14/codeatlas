"""`LLMClient.chat`: the one call the rest of CodeAtlas makes to a language model.

Order of work for each request: look in the cache; on a miss, try each provider in
priority order, retrying transient failures with backoff; record the answer and log
its token use.
"""

from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from codeatlas.llm.cache import LLMCache, cache_key
from codeatlas.llm.config import LLMConfig, load_llm_config
from codeatlas.llm.errors import CacheMissError, LLMTransientError, LLMUnavailableError
from codeatlas.llm.providers.base import Provider, resolve_model
from codeatlas.llm.types import LLMResponse, Message, ToolSpec

log = logging.getLogger(__name__)


class LLMClient:
    """Provider-agnostic chat with retry, fallback, record-and-replay and a usage log."""

    def __init__(
        self,
        providers: Sequence[Provider],
        cache: LLMCache | None = None,
        cache_mode: str = "read_write",
        namespace: str = "default",
        usage_log: Path | None = None,
        max_tries: int = 3,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.providers = list(providers)
        self.cache = cache if cache_mode != "off" else None
        self.cache_mode = cache_mode
        self.namespace = namespace
        self.usage_log = usage_log
        self.max_tries = max_tries
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._resolved: set[str] = set()

    @classmethod
    def from_config(cls, config: LLMConfig | None = None) -> LLMClient:
        """Build providers, cache and log paths from `codeatlas.toml` and the environment."""
        config = config or load_llm_config()
        providers = [_make_provider(name, config) for name in config.providers]
        cache = None if config.cache == "off" else LLMCache(config.cache_path)
        return cls(
            providers,
            cache=cache,
            cache_mode=config.cache,
            namespace=config.cache_namespace,
            usage_log=config.usage_log_path,
            max_tries=config.max_tries,
        )

    def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Answer from the cache when allowed, otherwise from the first provider that works.

        Raises `LLMRequestError` on a 400-class error (no fallback), `CacheMissError` in
        `replay_only` mode, and `LLMUnavailableError` when every provider failed.
        """
        key = cache_key(messages, tools, temperature, max_tokens, self.namespace)
        if self.cache is not None:
            hit = self.cache.get_chat(key)
            if hit is not None:
                return hit
            if self.cache_mode == "replay_only":
                raise CacheMissError(f"no cached answer for request {key[:12]}")
        response = self._call_providers(messages, tools, temperature, max_tokens)
        if self.cache is not None:
            self.cache.put_chat(key, response)
        return response

    def _call_providers(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None,
        temperature: float,
        max_tokens: int | None,
    ) -> LLMResponse:
        failures: list[str] = []
        for provider in self.providers:
            self._resolve_once(provider)
            for attempt in range(self.max_tries):
                started = time.monotonic()
                try:
                    response = provider.chat(messages, tools, temperature, max_tokens)
                except LLMTransientError as exc:
                    failures.append(str(exc))
                    log.warning("%s try %d/%d failed: %s", provider.name, attempt + 1,
                                self.max_tries, exc)
                    if attempt + 1 < self.max_tries:
                        self._sleep(self._backoff(attempt))
                    continue
                self._log_usage(response, time.monotonic() - started)
                return response
            log.warning("%s gave up after %d tries; trying the next provider", provider.name,
                        self.max_tries)
        raise LLMUnavailableError("every provider failed: " + " | ".join(failures))

    def _backoff(self, attempt: int) -> float:
        """Exponential delay with full jitter on top: 1s, 2s, 4s ... plus up to one base."""
        return self.backoff_seconds * (2**attempt) + self._rng.uniform(0, self.backoff_seconds)

    def _resolve_once(self, provider: Provider) -> None:
        """Check the configured model exists the first time a provider is used."""
        if provider.name not in self._resolved:
            self._resolved.add(provider.name)
            resolve_model(provider)

    def _log_usage(self, response: LLMResponse, seconds: float) -> None:
        if self.usage_log is None:
            return
        record = {
            "time": time.time(),
            "provider": response.provider,
            "model": response.model,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "latency_ms": round(seconds * 1000),
            "namespace": self.namespace,
        }
        self.usage_log.parent.mkdir(parents=True, exist_ok=True)
        with self.usage_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")


def _make_provider(name: str, config: LLMConfig) -> Provider:
    # Imported here so a test or tool that never calls a provider skips the SDK imports.
    if name == "groq":
        from codeatlas.llm.providers.groq import GroqProvider

        return GroqProvider(config.groq_model, timeout=config.timeout_seconds)
    from codeatlas.llm.providers.gemini import GeminiProvider

    return GeminiProvider(config.gemini_model, timeout=config.timeout_seconds)
