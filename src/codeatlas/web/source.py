"""Reading source lines from the indexed checkout, for the file and symbol pages.

The store holds the map, not the code. The code is in the folder that was indexed: a
local path, or the clone CodeAtlas made of a URL. Files are only read as text; nothing
from a repository is ever imported or run.
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.config import Config
from codeatlas.indexer.intake import IntakeError, looks_like_url, parse_repo_url
from codeatlas.models import Snapshot

MAX_LINES = 5000


def checkout_root(snapshot: Snapshot, config: Config) -> Path | None:
    """The folder a snapshot was indexed from, or None when it is no longer on disk.

    The same rule as `ToolContext.repo_root` in `agent/tools.py`.
    """
    local = Path(snapshot.source)
    if local.is_dir():
        return local
    if looks_like_url(snapshot.source):
        try:
            clone = config.repos_dir / parse_repo_url(snapshot.source).dirname
        except IntakeError:
            return None
        return clone if clone.is_dir() else None
    return None


def read_lines(root: Path | None, path: str) -> tuple[list[str] | None, str]:
    """The lines of one file, or None with the reason they cannot be shown.

    `path` comes from an address someone typed, so it is resolved and must still be
    inside the checkout: `../../secrets.txt` resolves outside it and is refused.
    """
    if root is None:
        return None, "The indexed checkout is no longer on disk, so there is no source to show."
    base = root.resolve()
    target = (base / path).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        return None, "This file is not in the checkout (it may have changed since indexing)."
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, f"This file could not be read: {exc.strerror or exc}."
    return text.splitlines(), ""
