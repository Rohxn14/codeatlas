"""Settings read from `codeatlas.toml`, with defaults that work when the file is missing.

The file is read from the directory CodeAtlas runs in, never from the repository being
indexed: an indexed repository must not be able to raise its own limits.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILE = "codeatlas.toml"


@dataclass(frozen=True, slots=True)
class Limits:
    """Bounds that keep a huge repository from stalling the indexer.

    When one is reached, indexing stops, keeps what it has, and names the limit in
    `Snapshot.limits_hit`.
    """

    max_files: int = 20_000
    max_file_bytes: int = 1_000_000
    max_seconds: float = 300.0
    max_history_commits: int = 2_000


@dataclass(frozen=True, slots=True)
class Config:
    """Everything CodeAtlas reads from `codeatlas.toml`."""

    limits: Limits = field(default_factory=Limits)
    workdir: Path = Path(".codeatlas")

    @property
    def repos_dir(self) -> Path:
        """Where URL intake keeps its clones."""
        return self.workdir / "repos"


def load_config(path: Path | None = None) -> Config:
    """Read `codeatlas.toml` (default: in the current directory); missing file means defaults.

    Unknown sections are ignored so later tasks can add their own (`[llm]`, ...).
    """
    path = path if path is not None else Path(CONFIG_FILE)
    if not path.is_file():
        return Config()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    limits = _read_limits(data.get("limits", {}))
    workdir = Path(data.get("paths", {}).get("workdir", ".codeatlas"))
    return Config(limits=limits, workdir=workdir)


def _read_limits(table: dict[str, object]) -> Limits:
    defaults = Limits()
    known = {"max_files", "max_file_bytes", "max_seconds", "max_history_commits"}
    unknown = set(table) - known
    if unknown:
        raise ValueError(f"unknown keys in [limits]: {sorted(unknown)}")
    values: dict[str, float | int] = {}
    for name in known:
        value = table.get(name, getattr(defaults, name))
        if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"[limits] {name} must be a positive number, got {value!r}")
        values[name] = value
    return Limits(
        max_files=int(values["max_files"]),
        max_file_bytes=int(values["max_file_bytes"]),
        max_seconds=float(values["max_seconds"]),
        max_history_commits=int(values["max_history_commits"]),
    )
