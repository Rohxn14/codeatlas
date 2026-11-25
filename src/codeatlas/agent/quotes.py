"""Does the code an answer quotes occur in the file it cites beside it? (D-63)

A citation that points at a real line proves that the line exists, not that it says what the
answer claims. On Nov 25 an answer listed eight callers of one function, five of them invented
(`contracts.validate(race, contracts.RACE, "Race")` at `backfill.py:108`), and all its citations
were valid. Invented code is easy to notice: its names are not in the file.

So on every line of an answer that holds both a citation and code in backticks, each word of the
code must be a word of a file cited on that line, or a name on the map (a symbol, a file, a folder):
"`classify_pit_passage` is reached by `test_laps.py`" names something real that is elsewhere. The
rule is loose on purpose: spacing, order and left-out arguments do not matter, and it does not judge
what the sentence says about the code. What it flags is a name that exists nowhere near.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from codeatlas.agent.snapshot_files import snapshot_bytes

_QUOTE = re.compile(r"`([^`\n]+)`")
_WORD = re.compile(r"[A-Za-z_]\w{2,}")
_CODE_CHARS = re.compile(r"[_.()=\[\]\"'*/<>{}]|[a-z][A-Z]")


@dataclass(frozen=True, slots=True)
class QuoteCheck:
    """One piece of quoted code, and the words of it that no file cited beside it holds."""

    text: str
    paths: tuple[str, ...]
    missing: tuple[str, ...]


def check_quotes(text: str, citations: list[Any], tools: Any, pattern: re.Pattern[str]
                 ) -> list[QuoteCheck]:
    """Every quote checked, found or not. `pattern` finds the citations on a line.

    A line whose cited files cannot be read (a checkout that is gone) is not judged.
    """
    path_of = {c.text: c.path for c in citations if c.valid}
    words: dict[str, frozenset[str] | None] = {}
    on_map: frozenset[str] | None = None
    checks: dict[tuple[str, tuple[str, ...]], QuoteCheck] = {}
    for line in text.splitlines():
        cited = [m.group(0) for m in pattern.finditer(line)]
        paths = tuple(dict.fromkeys(path_of[c] for c in cited if c in path_of))
        if not paths:
            continue
        for path in paths:
            if path not in words:
                words[path] = _words_of(tools, path)
        known = [words[p] for p in paths]
        if any(w is None for w in known):
            continue
        for quote in _QUOTE.findall(line):
            if not _is_code(quote, paths, tools, pattern):
                continue
            missing = tuple(dict.fromkeys(
                w for w in _WORD.findall(quote) if not any(w in k for k in known if k)))
            if missing and on_map is None:
                on_map = _names_on_map(tools)
            missing = tuple(w for w in missing if w not in (on_map or ()))
            checks[(quote, paths)] = QuoteCheck(quote, paths, missing)
    return list(checks.values())


def _is_code(quote: str, paths: tuple[str, ...], tools: Any, pattern: re.Pattern[str]) -> bool:
    """Code worth checking: not a plain word, a tool's name, a citation, or a file or folder."""
    if pattern.search(quote) or "::" in quote or not _CODE_CHARS.search(quote):
        return False
    if quote in {spec.name for spec in tools.specs}:
        return False
    bare = quote.removeprefix("./").rstrip("/")
    store, sid = tools.context.store, tools.context.snapshot_id
    if any(bare == p or p.endswith("/" + bare) or p.startswith(bare + "/") for p in paths):
        return False
    return store.module_for_path(sid, bare) is None


def _names_on_map(tools: Any) -> frozenset[str]:
    """Every word of a symbol's name or a file's path in the snapshot."""
    words: set[str] = set()
    for node in tools.context.store.nodes(tools.context.snapshot_id):
        words.update(_WORD.findall(node.name))
        words.update(_WORD.findall(node.path))
    return frozenset(words)


def _words_of(tools: Any, path: str) -> frozenset[str] | None:
    """Every word of a file as indexed, or None when it cannot be read."""
    ctx = tools.context
    record = ctx.file_record(path)
    if record is None:
        return None
    data = snapshot_bytes(ctx.repo_root(), ctx.snapshot.commit_sha, path, record.sha256)
    if data is None or b"\0" in data:
        return None
    return frozenset(_WORD.findall(data.decode("utf-8", errors="replace")))
