"""Shared test helpers: a throwaway local git repository instead of the network."""

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"


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
    (common on Windows) is seen as part of that repository.
    """
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))


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
