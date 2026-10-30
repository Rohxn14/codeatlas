"""Settings read from `codeatlas.toml`, with defaults that work when the file is absent.

The limits exist so a huge repository cannot stall the indexer: when one is reached,
indexing stops, keeps what it has, and names the limit in `Snapshot.limits_hit`.
"""

from __future__ import annotations

import time
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path

CONFIG_FILENAME = "codeatlas.toml"


@dataclass(frozen=True, slots=True)
class Config:
    """Every tunable value in one place; each field maps to one key in `codeatlas.toml`."""

    max_files: int = 20_000
    max_file_bytes: int = 1_000_000
    max_seconds: float = 300.0
    max_history_commits: int = 2_000
    data_dir: str = ".codeatlas"

    @property
    def repos_dir(self) -> Path:
        """Where cloned repositories live."""
        return Path(self.data_dir) / "repos"


# Section and key in the TOML file for each Config field.
_TOML_KEYS: dict[str, tuple[str, str]] = {
    "max_files": ("limits", "max_files"),
    "max_file_bytes": ("limits", "max_file_bytes"),
    "max_seconds": ("limits", "max_seconds"),
    "max_history_commits": ("history", "max_history_commits"),
    "data_dir": ("paths", "data_dir"),
}


def load_config(path: Path | None = None) -> Config:
    """Read `path`, or `./codeatlas.toml` when it exists; otherwise return the defaults.

    Only the tool's own config is read, never one inside an indexed repository, so a
    repository cannot raise its own limits.
    """
    if path is None:
        path = Path.cwd() / CONFIG_FILENAME
        if not path.is_file():
            return Config()
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return config_from_dict(data)


def config_from_dict(data: dict[str, object]) -> Config:
    """Build a Config from parsed TOML; unknown keys are ignored, wrong types raise."""
    defaults = Config()
    values: dict[str, object] = {}
    for item in fields(Config):
        section, key = _TOML_KEYS[item.name]
        table = data.get(section)
        if not isinstance(table, dict) or key not in table:
            continue
        values[item.name] = _coerce(item.name, table[key], getattr(defaults, item.name))
    return replace(defaults, **values)


def _coerce(name: str, value: object, default: object) -> object:
    if isinstance(default, str):
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string, got {value!r}")
        return value
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number, got {value!r}")
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value!r}")
    return type(default)(value)


class Deadline:
    """The time limit for one index, shared by discovery and parsing."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._end = time.monotonic() + seconds

    def expired(self) -> bool:
        return time.monotonic() >= self._end
