"""Read a unified diff into `Change`s: which files, and which lines of the new version."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from codeatlas.impact.models import Change

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_BODY = (" ", "-", "+", "\\")  # context, removed, added, "\ No newline at end of file"


@dataclass
class _Hunk:
    """One hunk while its body is read: which lines of the new file really changed.

    A hunk also prints unchanged lines round each edit (context). Those are counted
    to keep the line number right and are not marked. A run of removed lines with no
    added line beside it leaves nothing new to mark, so it marks the line just above
    where the text was: that line is usually in the same function. Text removed from
    the very top of a file marks line 0, which no symbol covers: the file still counts
    as changed, and nothing below is blamed.
    """

    header: tuple[int, int]  # what the `@@` line claims; used when there is no body
    line: int  # the number of the next line of the new file
    ranges: list[tuple[int, int]] = field(default_factory=list)
    has_body: bool = False
    removed: bool = False  # the run of changed lines being read has removed lines
    added: bool = False  # ... and added lines

    def take(self, first: str) -> None:
        """Read one body line by its first character."""
        self.has_body = True
        if first == "+":
            self._mark(self.line)
            self.added = True
            self.line += 1
        elif first == "-":
            self.removed = True
        elif first != "\\":  # context ends a run; "\ No newline" is not a line at all
            self._end_run()
            self.line += 1

    def result(self) -> list[tuple[int, int]]:
        self._end_run()
        return self.ranges if self.has_body else [self.header]

    def _end_run(self) -> None:
        if self.removed and not self.added:
            self._mark(self.line - 1)
        self.removed = self.added = False

    def _mark(self, number: int) -> None:
        """Add one line, growing the last range when the line touches it."""
        if self.ranges and number <= self.ranges[-1][1] + 1:
            start, end = self.ranges[-1]
            self.ranges[-1] = (start, max(end, number))
        else:
            self.ranges.append((number, number))


@dataclass
class _Section:
    """One file's part of the diff, filled in as its header and hunks are read."""

    git_path: str | None = None  # from `diff --git a/X b/Y`, the fallback for every other name
    old: str | None = None
    new: str | None = None
    renamed_from: str | None = None
    renamed_to: str | None = None
    added: bool = False
    deleted: bool = False
    seen_hunk: bool = False
    ranges: list[tuple[int, int]] = field(default_factory=list)

    def changes(self) -> list[Change]:
        """A section with no hunks (binary, mode-only, pure rename) is a whole-file change."""
        path = self.renamed_to or self.new or (None if self.added else self.old) or self.git_path
        if self.deleted:
            path = self.old or self.renamed_from or self.git_path
        if path is None:
            return []
        whole = self.added or self.deleted or not self.ranges
        found = [Change(path, () if whole else tuple(self.ranges))]
        # Every importer of the old path breaks, so a rename reports the old file too.
        old = self.renamed_from
        if old is None and self.git_path is not None and self.new and self.old != self.new:
            old = self.old
        if old and old != path:
            found.append(Change(old))
        return found


def parse_diff(text: str) -> list[Change]:
    """Changed files and line ranges from `git diff` (or plain `diff -u`) output.

    Ranges are in the new file's numbering, because the snapshot is the commit being
    changed *to*. Only added lines are marked, not the unchanged lines a hunk prints
    round them. A pure deletion has no new lines, so it marks the line just above where
    the removed text was. A hunk given as a header with no body marks the span the header
    names. Added, deleted, binary, mode-only and renamed-without-edits files have no
    ranges (the whole file); a rename also reports its old path.

    Hunk bodies are read by their line counts, so a removed SQL comment `-- x` or an
    added `++ y` is never taken for a file header.
    """
    sections: list[_Section] = []
    current: _Section | None = None
    hunk: _Hunk | None = None
    old_left = new_left = 0  # lines still owed to the open hunk
    for line in text.splitlines():
        if hunk is not None and (old_left > 0 or new_left > 0) and line[:1] in _BODY + ("",):
            hunk.take(line[:1])
            old_left, new_left = _consume(line, old_left, new_left)
            continue
        if hunk is not None and current is not None:
            current.ranges += hunk.result()
        hunk = None
        old_left = new_left = 0
        if line.startswith("diff --git "):
            current = _Section(git_path=_git_line_path(line[len("diff --git "):]))
            sections.append(current)
        elif line.startswith("--- "):
            if current is not None and current.git_path is not None and current.seen_hunk:
                continue  # headers come before the first hunk of a git section
            if current is None or current.git_path is None:
                current = _Section()  # a diff without git headers: one section per pair
                sections.append(current)
            current.old = _strip(line[4:])
        elif line.startswith("+++ ") and current is not None and not current.seen_hunk:
            current.new = _strip(line[4:])
            current.added = current.added or current.old is None
            current.deleted = current.deleted or current.new is None
        elif current is None:
            continue
        elif line.startswith("rename from "):
            current.renamed_from = _strip(line[len("rename from "):], prefixed=False)
        elif line.startswith("rename to "):
            current.renamed_to = _strip(line[len("rename to "):], prefixed=False)
        elif line.startswith("new file mode"):
            current.added = True
        elif line.startswith("deleted file mode"):
            current.deleted = True
        elif line.startswith("@@"):
            match = _HUNK.match(line)
            if match:
                current.seen_hunk = True
                old_left = int(match.group(2)) if match.group(2) is not None else 1
                new_left = int(match.group(4)) if match.group(4) is not None else 1
                start = int(match.group(3))
                # With no new lines the header names the line above the removed text.
                hunk = _Hunk((start, start + max(new_left, 1) - 1),
                             start if new_left else start + 1)
    if hunk is not None and current is not None:
        current.ranges += hunk.result()
    return [change for section in sections for change in section.changes()]


def _consume(line: str, old_left: int, new_left: int) -> tuple[int, int]:
    """Count one hunk body line against the hunk's old and new line totals."""
    first = line[:1]
    if first == "-":
        return old_left - 1, new_left
    if first == "+":
        return old_left, new_left - 1
    if first == "\\":
        return old_left, new_left
    return old_left - 1, new_left - 1  # context (some tools strip its leading space)


def _git_line_path(rest: str) -> str | None:
    """The new path from `a/X b/Y`, which is ambiguous when names contain spaces.

    Quoted names are exact. Unquoted, an unrenamed file has the same name twice, which
    fixes where the split is; otherwise split at the last ` b/`.
    """
    if rest.startswith('"') or rest.endswith('"'):
        quoted = re.findall(r'"(?:[^"\\]|\\.)*"|\S+', rest)
        return _strip(quoted[-1]) if quoted else None
    half = (len(rest) - 1) // 2
    if len(rest) % 2 == 1 and rest[half] == " " and _strip(rest[:half]) == _strip(rest[half + 1:]):
        return _strip(rest[half + 1:])
    if " b/" in rest:
        return _strip(rest[rest.rindex(" b/") + 1:])
    parts = rest.split(" ")
    return _strip(parts[-1]) if len(parts) == 2 else None


def _strip(name: str, prefixed: bool = True) -> str | None:
    """`a/x.py` -> `x.py`; `/dev/null` -> None; git's quoted `"d\\303\\251.py"` -> `dé.py`."""
    name = name.split("\t")[0].strip()
    if len(name) >= 2 and name[0] == name[-1] == '"':
        name = _unquote(name[1:-1])
    if name == "/dev/null":
        return None
    return name[2:] if prefixed and name[:2] in ("a/", "b/") else name


def _unquote(body: str) -> str:
    """Undo git's C-style quoting: backslash escapes and octal bytes of UTF-8."""
    try:
        raw = body.encode("latin-1").decode("unicode_escape").encode("latin-1")
        return raw.decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return body
