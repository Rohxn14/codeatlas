"""Shared fixtures: small git repositories built on the fly, never fetched from the network."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import git, write


@pytest.fixture
def make_repo(tmp_path: Path):
    """Build a git repository with the given files and one commit; returns its path."""

    def build(files: dict[str, str], name: str = "origin") -> Path:
        root = tmp_path / name
        root.mkdir()
        git(root, "init", "-q")
        for rel, content in files.items():
            write(root, rel, content)
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "first")
        return root

    return build
