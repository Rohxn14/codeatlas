from collections.abc import Callable
from itertools import count
from pathlib import Path

import pytest
from conftest import git
from test_manifests import records

from codeatlas.models import EdgeKind, FileRecord, Resolution
from codeatlas.repo import CoChangeAnalyzer
from codeatlas.repo.cochange import parse_log

SNAPSHOT = "s@0123456789ab"
_versions = count()


def commit(root: Path, changes: dict[str, str | None]) -> None:
    """Write (or, for None, delete) files and commit them."""
    for rel, text in changes.items():
        target = root / rel
        if text is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "change")


def edit(*paths: str) -> dict[str, str | None]:
    """New content for each path, different on every call."""
    version = next(_versions)
    return {p: f"version {version}\n" for p in paths}


def head_files(root: Path) -> list[FileRecord]:
    return [r for r in records(root) if not r.path.startswith(".git/")]


def run(root: Path, **settings: int) -> tuple[dict[tuple[str, str], tuple[float, dict]], dict]:
    """(source, target) -> (confidence, attrs) for each edge, and the report."""
    analyzer = CoChangeAnalyzer(**settings)
    nodes, edges = analyzer.analyze(root, head_files(root), SNAPSHOT)
    assert nodes == []
    found = {}
    for edge in edges:
        assert (edge.kind, edge.resolution) == (EdgeKind.CO_CHANGES, Resolution.HISTORY)
        key = (_path(edge.src_id), _path(edge.dst_id))
        found[key] = (round(edge.confidence, 4), edge.attrs)
    return found, analyzer.report


def _path(node_id: str) -> str:
    return node_id.removeprefix(SNAPSHOT + "/").removesuffix("::")


@pytest.fixture
def history(make_repo: Callable[..., Path]) -> Path:
    """a: 4 commits, b: 5, c: 2. Together: a+b 3, b+c 2, a+c 1."""
    root = make_repo(edit("a.py", "b.py", "c.py"))  # commit 1: a b c
    commit(root, edit("a.py", "b.py"))  # 2
    commit(root, edit("a.py", "b.py"))  # 3
    commit(root, edit("a.py"))  # 4
    commit(root, edit("b.py", "c.py"))  # 5
    commit(root, edit("b.py"))  # 6
    return root


def test_exact_directional_confidences(history: Path) -> None:
    found, report = run(history)
    assert found == {
        ("a.py", "b.py"): (0.75, {"support": 3, "source_commits": 4}),
        ("b.py", "a.py"): (0.6, {"support": 3, "source_commits": 5}),
    }
    assert report["status"] == "ok"
    assert report["commits_read"] == 6
    assert report["commits_analysed"] == 6
    assert report["edges"] == 2


def test_min_support_is_configurable(history: Path) -> None:
    found, _ = run(history, min_support=2)
    assert found[("b.py", "c.py")] == (0.4, {"support": 2, "source_commits": 5})
    assert found[("c.py", "b.py")] == (1.0, {"support": 2, "source_commits": 2})
    assert ("a.py", "c.py") not in found


def test_strongest_targets_are_kept(history: Path) -> None:
    found, report = run(history, min_support=2, max_targets=1)
    assert found[("b.py", "a.py")][0] == 0.6  # beats b -> c at 0.4
    assert ("b.py", "c.py") not in found
    assert report["targets_over_limit"] == 1


def test_history_limit_reads_only_recent_commits(history: Path) -> None:
    _, report = run(history, max_commits=2)
    assert report["commits_read"] == 2
    assert report["history_truncated"] is True


def test_large_commits_are_skipped(make_repo: Callable[..., Path]) -> None:
    root = make_repo(edit("a.py", "b.py"))
    commit(root, edit("a.py", "b.py"))
    commit(root, edit("a.py", "b.py", "x.py", "y.py"))  # a formatting sweep
    commit(root, edit("a.py", "b.py"))
    found, report = run(root, max_files_per_commit=3)
    assert found[("a.py", "b.py")] == (1.0, {"support": 3, "source_commits": 3})
    assert report["commits_skipped_large"] == 1
    assert report["commits_analysed"] == 3


def test_lockfiles_vendored_and_generated_files_are_ignored(make_repo: Callable[..., Path]) -> None:
    noise = ("package-lock.json", "vendor/lib.go", "web/app.min.js", "api/user_pb2.py")
    root = make_repo(edit("a.py", *noise))
    commit(root, edit("a.py", *noise))
    commit(root, edit("a.py", *noise))
    found, report = run(root)
    assert found == {}
    assert report["files_removed"] == {
        "vendored": 1, "lockfile": 1, "generated": 2, "not_in_snapshot": 0,
    }


def test_deleted_files_are_ignored(make_repo: Callable[..., Path]) -> None:
    root = make_repo(edit("a.py", "old.py", "b.py"))
    commit(root, edit("a.py", "old.py", "b.py"))
    commit(root, edit("a.py", "old.py", "b.py"))
    commit(root, {"old.py": None})
    found, report = run(root)
    assert set(found) == {("a.py", "b.py"), ("b.py", "a.py")}
    assert report["files_removed"]["not_in_snapshot"] == 1


def test_renamed_file_history_is_not_followed(make_repo: Callable[..., Path]) -> None:
    """`--no-renames`: a rename is a deletion plus a new file, so the old name's history
    stays with the old name and is dropped as not at HEAD."""
    root = make_repo(edit("a.py", "old.py"))
    commit(root, edit("a.py", "old.py"))
    commit(root, edit("a.py", "old.py"))
    git(root, "mv", "old.py", "new.py")
    git(root, "commit", "-q", "-m", "rename")
    found, _ = run(root)
    assert found == {}


def test_paths_with_spaces_and_unicode(make_repo: Callable[..., Path]) -> None:
    root = make_repo(edit("docs/read me.md", "src/café.py"))
    commit(root, edit("docs/read me.md", "src/café.py"))
    commit(root, edit("docs/read me.md", "src/café.py"))
    found, _ = run(root)
    assert ("docs/read me.md", "src/café.py") in found


def test_not_a_git_repository(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.py").write_text("x\n", encoding="utf-8")
    found, report = run(plain)
    assert found == {}
    assert report["status"] == "not a git repository"
    assert report["commits_read"] == 0


def test_folder_inside_another_repository_has_no_history_of_its_own(
    make_repo: Callable[..., Path],
) -> None:
    root = make_repo(edit("sub/a.py", "sub/b.py"))
    commit(root, edit("sub/a.py", "sub/b.py"))
    commit(root, edit("sub/a.py", "sub/b.py"))
    found, report = run(root / "sub")
    assert found == {}
    assert str(report["status"]).startswith("not the top of a git repository")


def test_repository_without_commits(tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    root.mkdir()
    git(root, "init", "-q")
    (root / "a.py").write_text("x\n", encoding="utf-8")
    found, report = run(root)
    assert found == {}
    assert report["status"] == "no commits"


def test_shallow_clone_is_reported(history: Path, tmp_path: Path) -> None:
    clone = tmp_path / "shallow"
    git(tmp_path, "clone", "-q", "--depth", "1", history.as_uri(), str(clone))
    found, report = run(clone)
    assert found == {}
    assert report["shallow"] is True
    assert report["commits_read"] == 1


def test_parse_log() -> None:
    text = "\x1eaaa\n\nsrc/a.py\nsrc/b.py\n\x1ebbb\n\x1eccc\n\nREADME.md\n"
    assert parse_log(text) == [["src/a.py", "src/b.py"], [], ["README.md"]]


def test_a_commit_of_exactly_the_limit_is_kept(make_repo: Callable[..., Path]) -> None:
    files = [f"m{i}.py" for i in range(4)]
    root = make_repo(dict.fromkeys(files, "start\n"))
    for _ in range(3):
        commit(root, edit(*files))  # every commit changes 4 files: exactly the limit
    found, report = run(root, max_files_per_commit=4)
    assert report["commits_skipped_large"] == 0
    assert ("m0.py", "m1.py") in found


def test_parse_log_reads_crlf_output() -> None:
    text = "\x1eaaa\r\n\r\na.py\r\nb.py\r\n\x1ebbb\r\n\r\nc.py\r\n"
    assert parse_log(text) == [["a.py", "b.py"], ["c.py"]]


def test_missing_git_is_reported_as_missing(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)
    _, report = run(tmp_path)
    assert report["status"].startswith("git not found")
