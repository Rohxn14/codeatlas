"""A tolerant JSON reader for tsconfig files, which allow comments and trailing commas."""

from __future__ import annotations

import json


def parse_jsonc(text: str) -> object:
    """Parse JSON that may hold `//` and `/* */` comments, trailing commas and a BOM.

    Raises `ValueError` when the text is still not JSON after cleaning, so the caller can
    report the file instead of crashing the whole resolution.
    """
    return json.loads(_strip_trailing_commas(_strip_comments(text.lstrip("﻿"))))


def _strip_comments(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = _string_end(text, i)
            out.append(text[i:j])
            i = j
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            out.append(" ")
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    """Drop a comma whose next non-space character closes an object or array."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = _string_end(text, i)
            out.append(text[i:j])
            i = j
            continue
        if ch == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _string_end(text: str, start: int) -> int:
    """Index just past the string literal that opens at `start`."""
    i = start + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == '"':
            return i + 1
        else:
            i += 1
    return len(text)
