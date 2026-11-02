"""Shared test helpers: a throwaway local git repository instead of the network."""

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"

# The eval harness (`eval/oracle/`) lives at the repository root, outside the installed
# package; its tests in tests/eval import it from there.
ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# tests/data holds sample source files for adapters to parse, including files named
# like tests (test_*.py, *_test.go). They are inputs, not tests, so pytest skips them.
collect_ignore = ["data"]


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


@pytest.fixture(autouse=True)
def git_stays_in_tmp_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop git from searching above the test's temporary folder.

    Without this, a test folder under a home directory that is itself a git repository
    (common on Windows) is seen as part of that repository. Git applies a ceiling only
    to folders strictly below it, so the ceiling is the parent of `tmp_path`: tests run
    git in `tmp_path` itself, and a ceiling equal to it would not stop the search.
    """
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[[dict[str, str]], Path]:
    """Create a git repository with the given files committed; returns its folder."""

    def factory(files: dict[str, str], name: str = "origin") -> Path:
        root = tmp_path / name
        root.mkdir()
        git(root, "init", "-q", "-b", "main")
        for rel, text in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "initial")
        return root

    return factory
