"""Test helpers: git with a fixed identity and file writing, shared by several test files."""

from __future__ import annotations

import subprocess
from pathlib import Path

DATA = Path(__file__).parent / "data"


def git(cwd: Path, *args: str) -> str:
    """Run git with a fixed identity, so commits work on any machine and CI runner."""
    command = [
        "git",
        "-c", "user.name=CodeAtlas Tests",
        "-c", "user.email=tests@example.invalid",
        "-c", "commit.gpgsign=false",
        "-c", "init.defaultBranch=main",
        *args,
    ]
    done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout


def write(root: Path, rel: str, content: str | bytes) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8", newline="\n")
    return path
