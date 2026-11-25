"""Split a documentation file into sections: one heading and the text under it.

A README answers questions the code cannot ("how do I install this?"). To make that
text searchable it is cut at its headings, so a search hit can point at lines 40 to 62
of `README.md` and not at the whole file. This module only cuts text; turning the
pieces into nodes is the text adapter's job.

Two heading styles are read:

- Markdown: `## Title` (one to six `#`), and a line underlined with `===` or `---`.
  Lines inside a fenced code block (three backticks or tildes) are never headings.
- reStructuredText: a line underlined with a row of one punctuation character at
  least as long as the title. The first character seen is level 1, the next level 2.

A section runs to the next heading of any level, so no line belongs to two sections.

A text file without headings (`.gitignore`, YAML, JSON, a script in a language with no
grammar) is cut into parts of at most `PART_LINES` lines instead (`split_parts`), so what
it says can be found although nothing in the code points at it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DOC_LANGUAGES = frozenset({"markdown", "rst"})
TOP_TITLE = "(top of file)"
PART_LINES = 60
PART_CHARS = 4000  # one section node keeps at most this much text
MAX_PARTS = 50  # per file: 3,000 lines of a lock file or a data file is plenty

_ATX = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_MD_UNDERLINE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_RST_UNDERLINE = re.compile(r"^([=\-`:'\"~^_*+#<>.])\1{2,}[ \t]*$")


@dataclass(frozen=True, slots=True)
class Section:
    """One heading and the lines under it, up to the next heading."""

    title: str
    level: int  # 1 is the top level; 0 is text before the first heading
    start_line: int  # the heading's line, 1-based
    end_line: int  # the last line before the next heading
    text: str  # the lines under the heading, without the heading itself


def split_sections(text: str, language: str) -> list[Section]:
    """The sections of one file, in order. A file with no headings is one section."""
    lines = text.splitlines()
    if not lines:
        return []
    found = _markdown_headings(lines) if language == "markdown" else _rst_headings(lines)
    # Each heading: (first line index, first body line index, level, title).
    starts = [(0, 0, 0, TOP_TITLE), *found]
    sections = []
    for i, (first, body, level, title) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(lines)
        content = "\n".join(lines[body:end]).strip()
        if level == 0 and not content:
            continue  # nothing before the first heading
        sections.append(Section(title, level, first + 1, max(end, first + 1), content))
    return sections


def split_parts(text: str) -> tuple[list[Section], int]:
    """Parts of a text file with no headings, and the last line they cover.

    The second value is smaller than the file's line count when the file is longer than
    `MAX_PARTS` parts, so the caller can say what was left out.
    """
    lines = text.splitlines()
    parts: list[Section] = []
    start = chars = 0
    for i, line in enumerate(lines):
        full = i > start and (i - start >= PART_LINES or chars + len(line) > PART_CHARS)
        if full:
            parts.append(_part(lines, start, i))
            if len(parts) == MAX_PARTS:
                return _with_text(parts), i
            start, chars = i, 0
        chars += len(line) + 1
    if start < len(lines):
        parts.append(_part(lines, start, len(lines)))
    return _with_text(parts), len(lines)


def _part(lines: list[str], start: int, end: int) -> Section:
    return Section(f"lines {start + 1}-{end}", 0, start + 1, end,
                   "\n".join(lines[start:end]).rstrip())


def _with_text(parts: list[Section]) -> list[Section]:
    return [part for part in parts if part.text.strip()]


def _markdown_headings(lines: list[str]) -> list[tuple[int, int, int, str]]:
    found = []
    fence = ""  # the marker that opened the code block being skipped
    for i, line in enumerate(lines):
        opened = _FENCE.match(line)
        if fence:
            if opened and opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence):
                fence = ""
            continue
        if opened:
            fence = opened.group(1)
            continue
        atx = _ATX.match(line)
        if atx:
            found.append((i, i + 1, len(atx.group(1)), atx.group(2).strip()))
        elif i > 0 and _MD_UNDERLINE.match(line) and _is_title(lines[i - 1]):
            # `Title` then `=====`: the heading starts on the line above.
            if found and found[-1][0] == i - 1:
                continue
            level = 1 if line.lstrip().startswith("=") else 2
            found.append((i - 1, i + 1, level, lines[i - 1].strip()))
    return found


def _rst_headings(lines: list[str]) -> list[tuple[int, int, int, str]]:
    found = []
    order: list[str] = []  # adornment characters in the order they first appear
    for i, line in enumerate(lines):
        under = _RST_UNDERLINE.match(line)
        if not under or i == 0 or not _is_title(lines[i - 1]):
            continue
        title = lines[i - 1].strip()
        if len(line.rstrip()) < len(title) or _RST_UNDERLINE.match(lines[i - 1]):
            continue
        char = under.group(1)
        if char not in order:
            order.append(char)
        # An overline (the same row above the title) belongs to the heading.
        over = i >= 2 and lines[i - 2].rstrip() == line.rstrip()
        found.append((i - 2 if over else i - 1, i + 1, order.index(char) + 1, title))
    return found


def _is_title(line: str) -> bool:
    """A line that can be underlined into a heading: some text, not a list or a table row."""
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith(("-", "*", "+", "|", ">", "#", "```"))
