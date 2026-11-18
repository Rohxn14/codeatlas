"""Reading the LLM keys from `.env` (D-45): only CodeAtlas's names, the shell wins.

Every value here is made up; no test reads the owner's real `.env`.
"""

import os
import sys
from pathlib import Path

import pytest

from codeatlas.cli import main
from codeatlas.envfile import KEY_NAMES, load_env_file


def write(path: Path, text: str, bom: bool = False) -> Path:
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return path


def test_only_codeatlas_names_are_taken(tmp_path: Path) -> None:
    env_file = write(tmp_path / ".env", "# a comment\n"
                     "GROQ_API_KEY=gsk-made-up\n"
                     "CODEATLAS_GROQ_MODEL=some-model\n"
                     "DATABASE_PASSWORD=another-projects-secret\n")
    environ: dict[str, str] = {}
    assert load_env_file(env_file, environ) == ["CODEATLAS_GROQ_MODEL", "GROQ_API_KEY"]
    assert environ == {"GROQ_API_KEY": "gsk-made-up", "CODEATLAS_GROQ_MODEL": "some-model"}


def test_a_variable_already_set_wins_over_the_file(tmp_path: Path) -> None:
    env_file = write(tmp_path / ".env", "GROQ_API_KEY=from-file\nGEMINI_API_KEY=from-file\n")
    environ = {"GROQ_API_KEY": "from-shell", "GEMINI_API_KEY": ""}
    assert load_env_file(env_file, environ) == ["GEMINI_API_KEY"]
    assert environ == {"GROQ_API_KEY": "from-shell", "GEMINI_API_KEY": "from-file"}


def test_values_are_read_exactly_as_written(tmp_path: Path) -> None:
    """Notepad's byte-order mark, quotes and `export` are handled; a `$` is kept."""
    env_file = write(tmp_path / ".env",
                     'export GROQ_API_KEY="gsk-a$b${c}"\nGEMINI_API_KEY=\n', bom=True)
    environ: dict[str, str] = {}
    assert load_env_file(env_file, environ) == ["GROQ_API_KEY"]  # an empty value sets nothing
    assert environ["GROQ_API_KEY"] == "gsk-a$b${c}"


def test_no_file_sets_nothing(tmp_path: Path) -> None:
    environ: dict[str, str] = {}
    assert load_env_file(tmp_path / ".env", environ) == [] and environ == {}


def test_a_test_calling_main_never_reads_dot_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    write(tmp_path / ".env", "GROQ_API_KEY=from-file\n")
    monkeypatch.chdir(tmp_path)
    assert main(["scan", str(tmp_path)]) == 0
    assert "GROQ_API_KEY" not in os.environ


def test_the_real_command_line_reads_dot_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in KEY_NAMES:
        monkeypatch.delenv(name, raising=False)  # restored, so the key does not leak on
    write(tmp_path / ".env", "GROQ_API_KEY=from-file\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codeatlas", "scan", str(tmp_path)])
    assert main() == 0
    assert os.environ["GROQ_API_KEY"] == "from-file"
