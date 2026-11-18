"""`LLMClient.chat`: the one call the rest of CodeAtlas makes to a language model.

Order of work for each request: look in the cache; on a miss, try each provider in
priority order, retrying server errors with backoff; record the answer and log its token
use. A provider that says "rate limited" (429) rests for as long as it asked, and the
request moves on; when every provider is resting, the client waits for the first one to
be free, up to `max_wait_seconds`.
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
from codeatlas.llm.errors import (
    CacheMissError,
    LLMEmptyResponseError,
    LLMRequestError,
    LLMTransientError,
    LLMUnavailableError,
)
from codeatlas.llm.providers.base import Provider, resolve_model
from codeatlas.llm.types import LLMResponse, Message, ToolSpec

log = logging.getLogger(__name__)

# How long a rate-limited provider rests when it does not say. Free tiers count tokens
# per minute, so a minute is the longest a per-minute limit can last.
DEFAULT_REST = 60.0

# Called with (seconds, provider label) just before the client waits for a rate limit.
OnWait = Callable[[float, str], None]


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
        max_wait_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if cache_mode == "replay_only" and cache is None:
            raise ValueError("cache_mode='replay_only' needs a cache; without one every call "
                             "would go to the network")
        self.providers = list(providers)
        self.cache = cache if cache_mode != "off" else None
        self.cache_mode = cache_mode
        self.namespace = namespace
        self.usage_log = usage_log
        self.max_tries = max_tries
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep
        self._rng = rng or random.Random()
        self.max_wait_seconds = max_wait_seconds
        self.on_wait: OnWait | None = None
        self._clock = clock
        # Keyed by position in `providers`: two providers can share a name (two Groq
        # models), and each has its own limits.
        self._rest_until: dict[int, float] = {}
        # (tokens left this minute, when the minute resets), from a provider's last answer.
        self._budget: dict[int, tuple[float, float]] = {}
        self._resolved: set[int] = set()
        self._re_resolved: set[int] = set()

    @classmethod
    def from_config(cls, config: LLMConfig | None = None) -> LLMClient:
        """Build providers, cache and log paths from `codeatlas.toml` and the environment."""
        config = config or load_llm_config()
        providers = [p for name in config.providers for p in _make_providers(name, config)]
        cache = None if config.cache == "off" else LLMCache(config.cache_path)
        return cls(
            providers,
            cache=cache,
            cache_mode=config.cache,
            namespace=config.cache_namespace,
            usage_log=config.usage_log_path,
            max_tries=config.max_tries,
            max_wait_seconds=config.max_wait_seconds,
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
        """Try each provider in order; when all that are left are resting, wait for one.

        A provider that failed this request for another reason (5xx, empty answer) is
        not tried again by the same request.
        """
        failures: list[str] = []
        done: set[int] = set()  # failed this request for a reason other than a rate limit
        waited = 0.0
        estimate = estimate_tokens(messages, tools)
        while True:
            for index, provider in enumerate(self.providers):
                if index in done or self._resting_for(index) > 0:
                    continue
                if self._does_not_fit(index, estimate):
                    failures.append(f"{_label(provider)}: about {estimate} tokens do not fit "
                                    f"in what is left of its minute")
                    continue
                response = self._try_provider(index, provider, messages, tools, temperature,
                                              max_tokens, failures, done, estimate)
                if response is not None:
                    return response
            resting = [i for i in range(len(self.providers))
                       if i not in done and self._resting_for(i) > 0]
            if not resting:
                break
            wait = min(self._resting_for(i) for i in resting)
            if waited + wait > self.max_wait_seconds:
                failures.append(f"still rate limited: the first provider is free again in "
                                f"{wait:.0f} s, beyond the {self.max_wait_seconds:.0f} s "
                                f"this client waits")
                break
            label = _label(self.providers[min(resting, key=self._resting_for)])
            log.warning("every provider is rate limited; waiting %.1f s for %s", wait, label)
            if self.on_wait is not None:
                self.on_wait(wait, label)
            self._sleep(wait)
            waited += wait
        raise LLMUnavailableError("every provider failed: " + " | ".join(failures))

    def _try_provider(
        self,
        index: int,
        provider: Provider,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None,
        temperature: float,
        max_tokens: int | None,
        failures: list[str],
        done: set[int],
        estimate: int = 0,
    ) -> LLMResponse | None:
        """One provider's tries for one request: the answer, or None to move on."""
        self._resolve_once(index, provider)
        attempt = 0
        while attempt < self.max_tries:
            started = time.monotonic()
            try:
                response = provider.chat(messages, tools, temperature, max_tokens)
            except LLMEmptyResponseError as exc:
                # The same request would come back empty again: move on at once.
                failures.append(str(exc))
                log.warning("%s: %s; trying the next provider", _label(provider), exc)
                done.add(index)
                return None
            except LLMRequestError as exc:
                if not self._model_was_retired(index, provider, exc):
                    raise
                continue  # retry once with the newly resolved model
            except LLMTransientError as exc:
                failures.append(str(exc))
                if exc.status == 429:
                    # A rate limit does not lift in a second or two: retrying at once only
                    # earns more 429s. Rest this provider and move on.
                    rest = exc.retry_after if exc.retry_after is not None else DEFAULT_REST
                    self._rest_until[index] = self._clock() + rest
                    log.warning("%s is rate limited; resting it for %.1f s",
                                _label(provider), rest)
                    return None
                attempt += 1
                log.warning("%s try %d/%d failed: %s", _label(provider), attempt,
                            self.max_tries, exc)
                if attempt < self.max_tries:
                    self._sleep(self._backoff(attempt - 1))
                continue
            limits = dict(getattr(provider, "last_limits", None) or {})
            self._remember_budget(index, limits)
            self._log_usage(response, time.monotonic() - started, limits, estimate)
            return response
        log.warning("%s gave up after %d tries; trying the next provider",
                    _label(provider), self.max_tries)
        done.add(index)
        return None

    def _remember_budget(self, index: int, limits: dict[str, float]) -> None:
        if "remaining_tokens" in limits and "reset_tokens" in limits:
            self._budget[index] = (limits["remaining_tokens"],
                                   self._clock() + limits["reset_tokens"])

    def _does_not_fit(self, index: int, estimate: int) -> bool:
        """True, and the provider rests until its minute resets, when the request is too big.

        Asking anyway would only earn a 429; a request bigger than a whole minute's budget
        (a fresh minute) is still sent, since nothing better can happen by waiting.
        """
        remaining, reset_at = self._budget.get(index, (float("inf"), 0.0))
        if self._clock() >= reset_at or estimate <= remaining:
            return False
        self._rest_until[index] = reset_at
        log.warning("%s: about %d tokens do not fit in the %d left this minute; resting it "
                    "%.1f s", _label(self.providers[index]), estimate, remaining,
                    reset_at - self._clock())
        return True

    def _resting_for(self, index: int) -> float:
        """Seconds until provider `index` may be asked again; 0 when it is not resting."""
        return max(0.0, self._rest_until.get(index, 0.0) - self._clock())

    def _backoff(self, attempt: int) -> float:
        """Exponential delay with full jitter on top: 1s, 2s, 4s ... plus up to one base."""
        return self.backoff_seconds * (2**attempt) + self._rng.uniform(0, self.backoff_seconds)

    def _resolve_once(self, index: int, provider: Provider) -> None:
        """Check the configured model exists the first time a provider is used."""
        if index not in self._resolved:
            self._resolved.add(index)
            resolve_model(provider)

    def _model_was_retired(self, index: int, provider: Provider, exc: LLMRequestError) -> bool:
        """After a 404, look the model up again once; True if a different one was found.

        A model retired since the first check is still configured, so the 404 says
        nothing about the request itself.
        """
        if exc.status != 404 or index in self._re_resolved:
            return False
        self._re_resolved.add(index)
        before = provider.model
        resolve_model(provider)
        return provider.model != before

    def _log_usage(self, response: LLMResponse, seconds: float,
                   limits: dict[str, float] | None = None, estimate: int = 0) -> None:
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
            # The guess made before sending, to measure how good `estimate_tokens` is.
            "estimated_input_tokens": estimate,
        }
        if limits:
            record["limits"] = limits
        self.usage_log.parent.mkdir(parents=True, exist_ok=True)
        with self.usage_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")


def estimate_tokens(messages: Sequence[Message], tools: Sequence[ToolSpec] | None) -> int:
    """A rough count of a request's input tokens: its characters divided by four.

    Only used to avoid sending a request a provider's minute cannot fit; the usage log
    keeps the estimate beside the real count so the ratio can be checked.
    """
    chars = sum(len(m.content or "") + len(json.dumps([c.to_dict() for c in m.tool_calls]))
                for m in messages)
    if tools:
        chars += len(json.dumps([[t.name, t.description, t.parameters] for t in tools]))
    return chars // 4


def _label(provider: Provider) -> str:
    """`groq openai/gpt-oss-20b`: the name alone is ambiguous once a provider has two models."""
    return f"{provider.name} {provider.model}"


def _make_providers(name: str, config: LLMConfig) -> list[Provider]:
    """One provider per model: Groq's main model, then each of its fallback models."""
    # Imported here so a test or tool that never calls a provider skips the SDK imports.
    if name == "groq":
        from codeatlas.llm.providers.groq import GroqProvider

        models = dict.fromkeys((config.groq_model, *config.groq_fallback_models))
        return [GroqProvider(model, timeout=config.timeout_seconds,
                             reasoning_effort=config.groq_reasoning_effort)
                for model in models]
    from codeatlas.llm.providers.gemini import GeminiProvider

    return [GeminiProvider(config.gemini_model, timeout=config.timeout_seconds,
                           thinking_level=config.gemini_thinking_level)]
