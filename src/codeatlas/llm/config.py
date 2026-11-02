"""Settings for the LLM layer: the `[llm]` section of `codeatlas.toml`, then the environment.

The shared `codeatlas.config.Config` belongs to the scaffold, so this section is read
here instead; only `[paths] data_dir` is shared, to put the cache beside the other data.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path

from codeatlas.config import CONFIG_FILENAME, config_from_dict

CACHE_MODES = ("off", "read_write", "replay_only")
PROVIDERS = ("groq", "gemini")
# "" turns the setting off, so the provider's own default applies.
GEMINI_THINKING_LEVELS = ("", "minimal", "low", "medium", "high")
GROQ_REASONING_EFFORTS = ("", "low", "medium", "high")


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Every tunable value of the LLM layer; field names match the keys under `[llm]`."""

    providers: tuple[str, ...] = PROVIDERS
    groq_model: str = "openai/gpt-oss-20b"
    gemini_model: str = "gemini-3.8-flash"
    # Thinking tokens count against the output limit, so a low default keeps short
    # answers from coming back empty; "minimal" suits cheap one-shot calls.
    gemini_thinking_level: str = "low"
    groq_reasoning_effort: str = "low"
    # About the network proxy's cutoff: a longer wait only delays the fallback.
    timeout_seconds: float = 30.0
    max_tries: int = 3
    cache: str = "read_write"
    cache_namespace: str = "default"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_batch_size: int = 64
    data_dir: str = ".codeatlas"

    @property
    def cache_path(self) -> Path:
        return Path(self.data_dir) / "llm_cache.sqlite"

    @property
    def usage_log_path(self) -> Path:
        return Path(self.data_dir) / "llm_usage.jsonl"


# Environment variable that overrides each field, when set.
ENV_KEYS: dict[str, str] = {
    "providers": "CODEATLAS_LLM_PROVIDERS",
    "groq_model": "CODEATLAS_GROQ_MODEL",
    "gemini_model": "CODEATLAS_GEMINI_MODEL",
    "gemini_thinking_level": "CODEATLAS_GEMINI_THINKING",
    "groq_reasoning_effort": "CODEATLAS_GROQ_REASONING",
    "timeout_seconds": "CODEATLAS_LLM_TIMEOUT",
    "cache": "CODEATLAS_LLM_CACHE",
    "cache_namespace": "CODEATLAS_LLM_NAMESPACE",
    "embedding_model": "CODEATLAS_EMBEDDING_MODEL",
}


def load_llm_config(
    path: Path | None = None, environ: Mapping[str, str] | None = None
) -> LLMConfig:
    """Read `path` (or `./codeatlas.toml` when present), then apply environment overrides."""
    data: dict[str, object] = {}
    if path is None:
        candidate = Path.cwd() / CONFIG_FILENAME
        path = candidate if candidate.is_file() else None
    if path is not None:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    section = data.get("llm", {})
    if not isinstance(section, dict):
        raise ValueError("[llm] must be a table")
    config = llm_config_from_dict(section, data_dir=config_from_dict(data).data_dir)
    return apply_env(config, os.environ if environ is None else environ)


def llm_config_from_dict(section: Mapping[str, object], data_dir: str = ".codeatlas") -> LLMConfig:
    """Build an LLMConfig from the parsed `[llm]` table; unknown keys are ignored."""
    defaults = LLMConfig(data_dir=data_dir)
    values = {
        item.name: _coerce(item.name, section[item.name], getattr(defaults, item.name))
        for item in fields(LLMConfig)
        if item.name in section and item.name != "data_dir"
    }
    return _validated(replace(defaults, **values))


def apply_env(config: LLMConfig, environ: Mapping[str, str]) -> LLMConfig:
    """Override fields from environment variables, parsed as their TOML counterparts."""
    values: dict[str, object] = {}
    for name, var in ENV_KEYS.items():
        raw = environ.get(var, "").strip()
        if not raw:
            continue
        default = getattr(config, name)
        value: object = raw
        if isinstance(default, tuple):
            value = [part.strip() for part in raw.split(",") if part.strip()]
        elif isinstance(default, float):
            value = float(raw)
        values[name] = _coerce(name, value, default)
    return _validated(replace(config, **values))


def _coerce(name: str, value: object, default: object) -> object:
    if isinstance(default, tuple):
        if not isinstance(value, list | tuple) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"llm.{name} must be a list of strings, got {value!r}")
        return tuple(value)
    if isinstance(default, str):
        if not isinstance(value, str):
            raise ValueError(f"llm.{name} must be a string, got {value!r}")
        return value
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"llm.{name} must be a positive number, got {value!r}")
    return type(default)(value)


def _validated(config: LLMConfig) -> LLMConfig:
    if config.cache not in CACHE_MODES:
        raise ValueError(f"llm.cache must be one of {CACHE_MODES}, got {config.cache!r}")
    if config.gemini_thinking_level not in GEMINI_THINKING_LEVELS:
        raise ValueError(f"llm.gemini_thinking_level must be one of {GEMINI_THINKING_LEVELS}")
    if config.groq_reasoning_effort not in GROQ_REASONING_EFFORTS:
        raise ValueError(f"llm.groq_reasoning_effort must be one of {GROQ_REASONING_EFFORTS}")
    unknown = [p for p in config.providers if p not in PROVIDERS]
    if unknown or not config.providers:
        raise ValueError(f"llm.providers must be a non-empty list from {PROVIDERS}")
    return config
