"""UTF-8 output for a real command line, even where Windows would pick its code page."""

import io
import sys
from pathlib import Path

import pytest

from codeatlas.cli import main
from codeatlas.console import utf8_output

TEXT = "non‑breaking hyphen, ’curly’ quotes, 日本"


def legacy_stream() -> tuple[io.BytesIO, io.TextIOWrapper]:
    """What Python gives a redirected stdout on Windows: the ANSI code page."""
    raw = io.BytesIO()
    return raw, io.TextIOWrapper(raw, encoding="cp1252")


def test_the_legacy_code_page_cannot_hold_these_characters() -> None:
    _, stream = legacy_stream()
    with pytest.raises(UnicodeEncodeError):  # the crash seen on Nov 19
        stream.write(TEXT)


def test_output_is_switched_to_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    raw, stream = legacy_stream()
    monkeypatch.setattr(sys, "stdout", stream)
    utf8_output()
    print(TEXT)
    stream.flush()
    assert TEXT in raw.getvalue().decode("utf-8")


def test_a_stream_that_is_not_a_text_wrapper_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = io.StringIO()
    monkeypatch.setattr(sys, "stdout", fake)
    utf8_output()
    assert sys.stdout is fake


def test_the_real_command_line_writes_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("stdout", "stderr"):
        monkeypatch.setattr(sys, name, legacy_stream()[1])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codeatlas", "scan", str(tmp_path)])
    assert main() == 0
    assert sys.stdout.encoding == "utf-8" and sys.stderr.encoding == "utf-8"


def test_a_test_calling_main_keeps_its_own_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, stream = legacy_stream()
    monkeypatch.setattr(sys, "stdout", stream)
    assert main(["scan", str(tmp_path)]) == 0
    assert stream.encoding == "cp1252"
