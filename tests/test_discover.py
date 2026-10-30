import hashlib
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from codeatlas.config import Config
from codeatlas.indexer.discover import Discovery, discover, language_for
from codeatlas.indexer.registry import Registry
from codeatlas.models import Tier

FILES = {
    "src/app.py": "def main():\n    pass\n",
    "src/web/App.tsx": "export const App = () => null;\n",
    "src/web/util.js": "function f() {}\n",
    "cmd/main.go": "package main\n",
    "README.md": "# hello\n",
    "notes.unknownext": "plain\n",
    "node_modules/pkg/index.js": "module.exports = 1;\n",
    "dist/bundle.js": "x\n",
    "static/app.min.js": "var a=1;\n",
    "logs/run.log": "ignored by .gitignore\n",
    "src/secret.py": "ignored by a nested .gitignore\n",
    ".gitignore": "logs/\n",
    "src/.gitignore": "secret.py\n",
}


def write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def run(root: Path, config: Config | None = None) -> Discovery:
    return discover(root, config or Config(), Registry().tier_for)


@pytest.fixture(params=["walk", "git"])
def tree(request: pytest.FixtureRequest, tmp_path: Path, make_repo: Callable[..., Path]) -> Path:
    """The same files, once as a plain folder and once as a git repository."""
    if request.param == "git":
        return make_repo(FILES)
    root = tmp_path / "plain"
    write_tree(root, FILES)
    return root


def test_lists_and_ignores(tree: Path) -> None:
    found = run(tree)
    paths = {f.path for f in found.files}
    assert {"src/app.py", "src/web/App.tsx", "src/web/util.js", "cmd/main.go"} <= paths
    assert "README.md" in paths and "notes.unknownext" in paths
    for ignored in ("logs/run.log", "src/secret.py"):
        assert ignored not in paths
    assert not any(p.startswith(("node_modules/", "dist/")) for p in paths)
    by_path = {f.path: f for f in found.files}
    assert by_path["static/app.min.js"].tier is Tier.TEXT
    assert found.skip_reasons == {"static/app.min.js": "minified"}


def test_excluded_folders_are_recorded_once_with_file_count(tree: Path) -> None:
    folders = {(s.path, s.reason, s.file_count) for s in run(tree).skipped}
    assert folders == {
        ("dist", "excluded directory", 1),
        ("node_modules", "excluded directory", 1),
    }


def test_nested_excluded_folder_counts_every_file(tmp_path: Path) -> None:
    write_tree(tmp_path, {"web/node_modules/a/x.js": "", "web/node_modules/b/y.js": "", "z.py": ""})
    found = run(tmp_path)
    assert [f.path for f in found.files] == ["z.py"]
    assert [(s.path, s.file_count) for s in found.skipped] == [("web/node_modules", 2)]


def test_languages_and_tiers(tree: Path) -> None:
    by_path = {f.path: f for f in run(tree).files}
    assert (by_path["src/app.py"].language, by_path["src/app.py"].tier) == (
        "python",
        Tier.DEEP,
    )
    assert by_path["src/web/App.tsx"].language == "tsx"
    assert by_path["src/web/util.js"].language == "javascript"
    assert by_path["cmd/main.go"].language == "go"
    assert (by_path["README.md"].language, by_path["README.md"].tier) == ("markdown", Tier.TEXT)
    assert (by_path["notes.unknownext"].language, by_path["notes.unknownext"].tier) == (
        "text",
        Tier.TEXT,
    )


def test_forward_slash_paths_and_hashes(tree: Path) -> None:
    for record in run(tree).files:
        assert "\\" not in record.path
        assert not record.path.startswith("/")
        data = (tree / record.path).read_bytes()
        assert record.sha256 == hashlib.sha256(data).hexdigest()
        assert record.size_bytes == len(data)


def test_git_mode_used_for_git_repo(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    assert run(make_repo({"a.py": "x = 1\n"})).used_git
    plain = tmp_path / "plain"
    plain.mkdir()
    assert not run(plain).used_git


def test_binary_and_large_files_stay_as_text_records_with_reason(tmp_path: Path) -> None:
    (tmp_path / "image.py").write_bytes(b"\x89PNG\x00\x00binary")
    (tmp_path / "big.py").write_text("x = 1\n" * 50, encoding="utf-8")
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    found = run(tmp_path, replace(Config(), max_file_bytes=100))
    tiers = {f.path: f.tier for f in found.files}
    assert tiers == {"big.py": Tier.TEXT, "image.py": Tier.TEXT, "ok.py": Tier.DEEP}
    assert found.skip_reasons["image.py"] == "binary"
    assert found.skip_reasons["big.py"].startswith("over max_file_bytes")
    assert "ok.py" not in found.skip_reasons
    big = next(f for f in found.files if f.path == "big.py")
    assert big.sha256 == hashlib.sha256((tmp_path / "big.py").read_bytes()).hexdigest()
    assert found.limits_hit == ("max_file_bytes",)


def test_tracked_file_in_excluded_dir_is_reported(make_repo: Callable[..., Path]) -> None:
    root = make_repo({"vendor.py": "x = 1\n", "build/gen.py": "y = 2\n"})
    found = run(root)
    assert [f.path for f in found.files] == ["vendor.py"]
    assert [(s.path, s.reason, s.file_count) for s in found.skipped] == [
        ("build", "excluded directory", 1)
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need extra rights on Windows")
def test_symlinked_folder_is_recorded_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("x = 1\n", encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("y = 2\n", encoding="utf-8")
    (root / "link").symlink_to(outside, target_is_directory=True)
    found = run(root)
    assert [f.path for f in found.files] == ["a.py"]
    assert [(s.path, s.reason) for s in found.skipped] == [("link", "symlink")]


@pytest.mark.parametrize(
    ("path", "language"),
    [
        ("a/b.ts", "typescript"),
        ("a/b.tsx", "tsx"),
        ("a/b.mjs", "javascript"),
        ("a/b.cjs", "javascript"),
        ("a/b.jsx", "javascript"),
        ("a/B.java", "java"),
        ("a/b.rs", "rust"),
        ("a/b.cs", "c_sharp"),
        ("a/b.PY", "python"),
        ("docker/Dockerfile", "dockerfile"),
        ("LICENSE", "text"),
    ],
)
def test_language_for(path: str, language: str) -> None:
    assert language_for(path) == language
