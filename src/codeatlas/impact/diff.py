"""Read a unified diff into `Change`s: which files, and which lines of the new version."""

from __future__ import annotations

import re

from codeatlas.impact.models import Change

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_diff(text: str) -> list[Change]:
    """Changed files and line ranges from `git diff` output.

    Ranges are in the new file's numbering, because the snapshot is the commit being
    changed *to*. A pure deletion has no new lines, so it marks the line where the
    removed text used to be. A deleted file keeps its old path and no ranges; a
    new file has no ranges either (the whole file is new).
    """
    changes: list[Change] = []
    path: str | None = None
    ranges: list[tuple[int, int]] = []
    whole_file = False

    def flush() -> None:
        if path is not None:
            changes.append(Change(path, () if whole_file else tuple(ranges)))

    old_path: str | None = None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            flush()
            path, ranges, whole_file, old_path = None, [], False, None
        elif line.startswith("--- "):
            old_path = _strip(line[4:])
        elif line.startswith("+++ "):
            new = _strip(line[4:])
            path = new or old_path
            whole_file = new is None or old_path is None  # added or deleted
        elif line.startswith("@@"):
            match = _HUNK.match(line)
            if match and path is not None:
                start = int(match.group(3))
                length = int(match.group(4)) if match.group(4) is not None else 1
                ranges.append((start, start + max(length, 1) - 1))
    flush()
    return changes


def _strip(name: str) -> str | None:
    """`a/x.py` -> `x.py`; `/dev/null` -> None."""
    name = name.split("\t")[0].strip().strip('"')
    if name == "/dev/null":
        return None
    return name[2:] if name[:2] in ("a/", "b/") else name
