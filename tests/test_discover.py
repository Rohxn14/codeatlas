import hashlib
import time
from pathlib import Path

import pytest
from helpers import write

from codeatlas.config import Limits
from codeatlas.indexer.discover import detect_language, discover, extensions_for
from codeatlas.models import Tier


def _tier(language: str) -> Tier:
    """A stand-in for the registry, so these tests do not depend on grammar packages."""
    return Tier.STRUCTURAL if language in {"python", "go", "typescript"} else Tier.TEXT


def _tree(root: Path) -> None:
    write(root, "src/app.py", "def main():\n    pass\n")
    write(root, "src/web/client.ts", "export const x = 1;\n")
    write(root, "cmd/main.go", "package main\n")
    write(root, "README.md", "# hi\n")
    write(root, "LICENSE", "MIT\n")
    write(root, "node_modules/lib/index.js", "module.exports = 1;\n")
    write(root, "pkg/build/out.py", "x = 1\n")
    write(root, "static/app.min.js", "var a=1;\n")
    write(root, "logo.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00")
    write(root, "big.py", "x = 1\n" * 50)
    write(root, ".gitignore", "*.log\nsecret/\n")
    write(root, "debug.log", "noise\n")
    write(root, "secret/key.py", "KEY = 1\n")
    write(root, "sub/.gitignore", "local.py\n")
    write(root, "sub/local.py", "x = 1\n")
    write(root, "sub/kept.py", "x = 1\n")


def test_walk_outside_git(tmp_path: Path) -> None:
    _tree(tmp_path)
    found = discover(tmp_path, Limits(max_file_bytes=200), tier_for=_tier)
    paths = [f.path for f in found.files]
    assert paths == [
        ".gitignore",
        "LICENSE",
        "README.md",
        "cmd/main.go",
        "src/app.py",
        "src/web/client.ts",
        "sub/.gitignore",
        "sub/kept.py",
    ]
    skipped = {s.path: s.reason for s in found.skipped}
    assert skipped["node_modules"] == "excluded directory"
    assert skipped["pkg/build"] == "excluded directory"
    assert skipped["static/app.min.js"] == "minified"
    assert skipped["logo.png"] == "binary"
    assert skipped["big.py"].startswith("over max_file_bytes")
    assert "debug.log" not in skipped and "secret/key.py" not in skipped  # ignored by git rules
    assert found.limits_hit == ()


def test_languages_tiers_and_hashes(tmp_path: Path) -> None:
    _tree(tmp_path)
    found = {f.path: f for f in discover(tmp_path, tier_for=_tier).files}
    assert found["src/app.py"].language == "python"
    assert found["src/app.py"].tier is Tier.STRUCTURAL
    assert found["src/web/client.ts"].language == "typescript"
    assert found["README.md"].language == "markdown"
    assert found["README.md"].tier is Tier.TEXT
    assert found["LICENSE"].language == "text"
    record = found["cmd/main.go"]
    assert record.size_bytes == len(b"package main\n")
    assert record.sha256 == hashlib.sha256(b"package main\n").hexdigest()
    assert all("\\" not in path for path in found)


def test_git_listing_uses_tracked_and_untracked_files(make_repo) -> None:
    root = make_repo(
        {
            "a.py": "x = 1\n",
            ".gitignore": "ignored.py\n",
            "node_modules/x.js": "1\n",  # committed by mistake; still skipped
        }
    )
    write(root, "new.py", "y = 1\n")  # untracked, not ignored
    write(root, "ignored.py", "z = 1\n")
    found = discover(root, tier_for=_tier)
    assert [f.path for f in found.files] == [".gitignore", "a.py", "new.py"]
    assert [(s.path, s.reason) for s in found.skipped] == [("node_modules", "excluded directory")]


def test_subfolder_of_git_repo_gives_relative_paths(make_repo) -> None:
    root = make_repo({"pkg/a.py": "x = 1\n", "b.py": "y = 1\n"})
    found = discover(root / "pkg", tier_for=_tier)
    assert [f.path for f in found.files] == ["a.py"]


def test_max_files_stops_discovery(tmp_path: Path) -> None:
    for i in range(5):
        write(tmp_path, f"m{i}.py", "x = 1\n")
    found = discover(tmp_path, Limits(max_files=3), tier_for=_tier)
    assert [f.path for f in found.files] == ["m0.py", "m1.py", "m2.py"]
    assert found.limits_hit == ("max_files",)


def test_deadline_stops_discovery(tmp_path: Path) -> None:
    write(tmp_path, "a.py", "x = 1\n")
    found = discover(tmp_path, tier_for=_tier, deadline=time.monotonic() - 1)
    assert found.files == ()
    assert found.limits_hit == ("max_seconds",)


@pytest.mark.parametrize(
    ("path", "language"),
    [
        ("a/b.ts", "typescript"),
        ("a/b.tsx", "tsx"),
        ("a/b.jsx", "javascript"),
        ("a/b.mjs", "javascript"),
        ("a/b.cjs", "javascript"),
        ("A.JAVA", "java"),
        ("x.rs", "rust"),
        ("x.cs", "c_sharp"),
        ("x.kt", "kotlin"),
        ("Dockerfile", "dockerfile"),
        ("notes", "text"),
    ],
)
def test_detect_language(path: str, language: str) -> None:
    assert detect_language(path) == language


def test_extensions_for() -> None:
    assert extensions_for("javascript") == (".cjs", ".js", ".jsx", ".mjs")
    assert extensions_for("nothing") == ()


def test_default_tiers_come_from_the_registry(tmp_path: Path) -> None:
    write(tmp_path, "a.go", "package a\n")
    write(tmp_path, "a.kt", "fun main() {}\n")
    tiers = {f.path: f.tier for f in discover(tmp_path).files}
    assert tiers == {"a.go": Tier.STRUCTURAL, "a.kt": Tier.TEXT}
