"""Fixtures: a hand-built snapshot over a real checkout folder."""

from pathlib import Path

import pytest

from codeatlas.store import GraphStore

from .support import FILES, populate


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    for rel, text in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def store(source_dir: Path) -> GraphStore:
    s = GraphStore(":memory:")
    populate(s, str(source_dir))
    return s
