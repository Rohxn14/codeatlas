"""What a real command line sets up before it prints anything: UTF-8 output."""

from __future__ import annotations

import codecs
import io
import sys


def utf8_output() -> None:
    """Make stdout and stderr write UTF-8, whatever Windows would pick for a file or pipe.

    Sent to a file or a pipe on Windows, Python writes the ANSI code page (cp1252 on the
    owner's machine), which has no non-breaking hyphen (U+2011), no curly quote, and no
    non-Latin script at all. Answers and source code hold such characters, so
    `codeatlas ask ... > answer.txt` crashed with UnicodeEncodeError after the answer
    was made (Nov 19). A console window is not affected: Python writes Unicode to it
    directly. A stream that is not a plain text wrapper (a test's capture) is left as is.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and _codec(stream.encoding) != "utf-8":
            stream.reconfigure(encoding="utf-8")


def _codec(name: str | None) -> str:
    """The codec's canonical name ("UTF8" and "utf_8" are both "utf-8"), or ""."""
    try:
        return codecs.lookup(name or "").name
    except LookupError:
        return ""
