"""Files that name other files: a README that links an image, a workflow that installs
`requirements.txt`, a settings file that lists pages (D-62).

Imports and calls join code to code. Everything else used to float: on PitwallOS 116 of 249
files had no edge but containment (Nov 25). Many of those are named somewhere, and a name in a
text is a fact that can be read without understanding the language it is in.

A name is looked up the way a reader would: next to the file that holds it, then from the
repository's root, then, when only one file could be meant, anywhere. Each way has its own
confidence, and none of them claims that the file is *used*: only that it is named. The impact
engine does not follow these edges.

Code naming code is left out, because imports and calls say that better. At least one end of
every edge is a text-tier file: documentation, settings, data, an image.
"""

from __future__ import annotations

import posixpath
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from codeatlas.indexer.discover import MINIFIED_SUFFIXES, is_secret_path
from codeatlas.models import (
    Edge,
    EdgeKind,
    FileRecord,
    Node,
    Resolution,
    Tier,
    make_key,
    make_node_id,
)

MAX_SOURCE_BYTES = 500_000  # longer is a lock file or data, which names thousands of things
MAX_FOLDER_FILES = 20  # naming a larger folder says nothing about one file in it
PATH_CONFIDENCE = 1.0
NAME_CONFIDENCE = 0.8
GUESS_CONFIDENCE = 0.3
# A path or a file name: parts joined by `/`, perhaps ending in one.
_TOKEN = re.compile(r"[\w.@+-]+(?:/[\w.@+-]+)*/?")


@dataclass(frozen=True, slots=True)
class _Found:
    path: str
    confidence: float
    resolution: Resolution
    line: int


class ReferenceAnalyzer:
    """One REFERENCES edge from a file to each other file its text names."""

    name = "references"

    def analyze(
        self, root: Path, files: Sequence[FileRecord], snapshot_id: str
    ) -> tuple[list[Node], list[Edge]]:
        lookup = _Lookup(files)
        text_tier = {f.path for f in files if f.tier is Tier.TEXT}
        edges: list[Edge] = []
        for record in files:
            text = _readable(root, record)
            if text is None:
                continue
            best: dict[str, _Found] = {}
            for found in lookup.named_in(record.path, text):
                if record.path not in text_tier and found.path not in text_tier:
                    continue
                known = best.get(found.path)
                if known is None or found.confidence > known.confidence:
                    best[found.path] = found
            src = make_node_id(snapshot_id, make_key(record.path, ""))
            edges += [
                Edge(src, make_node_id(snapshot_id, make_key(f.path, "")), EdgeKind.REFERENCES,
                     f.confidence, f.resolution, f.line)
                for f in sorted(best.values(), key=lambda f: f.path)
            ]
        return [], edges


def _readable(root: Path, record: FileRecord) -> str | None:
    """A file's text, or None when it is binary, long, minified or may hold secrets."""
    if (record.size_bytes > MAX_SOURCE_BYTES or is_secret_path(record.path)
            or record.path.lower().endswith(MINIFIED_SUFFIXES)):
        return None
    try:
        data = root.joinpath(*record.path.split("/")).read_bytes()
    except OSError:
        return None
    return None if b"\0" in data else data.decode("utf-8", errors="replace")


class _Lookup:
    """The files of a snapshot by path, by name, by the end of a path and by folder."""

    def __init__(self, files: Iterable[FileRecord]) -> None:
        self.paths = {f.path for f in files}
        self.by_name: dict[str, list[str]] = defaultdict(list)
        self.by_end: dict[str, list[str]] = defaultdict(list)
        self.in_folder: dict[str, list[str]] = defaultdict(list)
        for path in sorted(self.paths):
            folder, _, name = path.rpartition("/")
            self.by_name[name].append(path)
            self.in_folder[folder].append(path)
            parts = path.split("/")
            for i in range(1, len(parts) - 1):  # `pipeline/lake.py` for `src/pipeline/lake.py`
                self.by_end["/".join(parts[i:])].append(path)

    def named_in(self, path: str, text: str) -> Iterable[_Found]:
        folder = path.rpartition("/")[0]
        for number, line in enumerate(text.splitlines(), start=1):
            for match in _TOKEN.finditer(line):
                token = match.group(0).rstrip(".")
                if "/" not in token and "." not in token:
                    continue
                for target, confidence, resolution in self._resolve(token, folder):
                    if target != path:
                        yield _Found(target, confidence, resolution, number)

    def _resolve(self, token: str, folder: str) -> list[tuple[str, float, Resolution]]:
        if "/" not in token:
            return self._by_name(token, folder)
        for base in (folder, ""):
            full = posixpath.normpath(posixpath.join(base, token))
            if full in self.paths:
                return [(full, PATH_CONFIDENCE, Resolution.DIRECT)]
            inside = self.in_folder.get(full, []) if full not in (".", "") else []
            if 0 < len(inside) <= MAX_FOLDER_FILES:
                share = min(GUESS_CONFIDENCE, 1 / len(inside))
                return [(p, share, Resolution.NAME_GUESS) for p in inside]
        ends = self.by_end.get(token.rstrip("/"), [])
        return [(ends[0], GUESS_CONFIDENCE, Resolution.NAME_GUESS)] if len(ends) == 1 else []

    def _by_name(self, name: str, folder: str) -> list[tuple[str, float, Resolution]]:
        for near in (f"{folder}/{name}" if folder else name, name):
            if near in self.paths:
                return [(near, NAME_CONFIDENCE, Resolution.CONVENTION)]
        found = self.by_name.get(name, [])
        return [(found[0], GUESS_CONFIDENCE, Resolution.NAME_GUESS)] if len(found) == 1 else []
