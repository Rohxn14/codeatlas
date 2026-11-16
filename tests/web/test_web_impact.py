"""The impact page: reading a change from git or a pasted diff, and showing what it reaches."""

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.config import Config
from codeatlas.impact.engine import ImpactEngine
from codeatlas.impact.evaluate import all_test_files
from codeatlas.impact.models import Change
from codeatlas.indexer.pipeline import index_repository
from codeatlas.models import Snapshot
from codeatlas.store import GraphStore
from codeatlas.web import create_app, snapshot_slug
from codeatlas.web.changes import (
    MAX_DIFF_BYTES,
    ChangeError,
    at_snapshot,
    commit_changes,
    pasted_changes,
    recent_commits,
    worktree_changes,
)
from codeatlas.web.data import load_snapshot
from codeatlas.web.impact_page import impact_view

UTIL = "def helper():\n    pass\n\n\ndef apply_gate():\n    return 1\n"
REPO = {
    "app/service.py": (
        "from lib.util import helper\n\n\n"
        "class Service:\n"
        "    def save(self):\n"
        "        helper()\n"
    ),
    "lib/util.py": UTIL,
    "tests/test_util.py": "from lib.util import helper\n\n\ndef test_helper():\n    helper()\n",
    "tests/test_other.py": "def test_nothing():\n    assert True\n",
}
DIFF = (
    "diff --git a/lib/util.py b/lib/util.py\n"
    "--- a/lib/util.py\n"
    "+++ b/lib/util.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def helper():\n"
    "-    pass\n"
    "+    return 2\n"
)

Site = tuple[Path, Config, Snapshot, Path]


def run_git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          check=True)
    return done.stdout.strip()


@pytest.fixture
def site(make_repo: Callable[..., Path], tmp_path: Path) -> Site:
    """A repository with two commits, indexed at the second: (database, config, snapshot,
    checkout). The second commit changes only the body of `helper`."""
    config = Config(data_dir=(tmp_path / "data").as_posix())
    db_path = tmp_path / "data" / "codeatlas.db"
    repo = make_repo(REPO, name="demo")
    (repo / "lib" / "util.py").write_text(UTIL.replace("pass", "return 2"), encoding="utf-8")
    run_git(repo, "commit", "-q", "-am", "helper returns 2")
    report = index_repository(str(repo), config, db_path)
    with GraphStore(db_path) as store:
        snapshot = store.get_snapshot(report.snapshot["id"])
    assert snapshot is not None
    return db_path, config, snapshot, repo


@pytest.fixture
def http(site: Site) -> tuple[TestClient, str]:
    return TestClient(create_app(site[0], site[1])), f"/s/{snapshot_slug(site[2].id)}/impact"


def changed_by(site: Site, changes: tuple[Change, ...]) -> tuple[str, ...]:
    with GraphStore(site[0]) as store:
        return ImpactEngine(store, site[2].id).impact(changes).changed


# Reading a change from git


def test_recent_commits_start_at_the_indexed_commit(site: Site) -> None:
    commits = recent_commits(site[3], site[2])
    assert [c.subject for c in commits] == ["helper returns 2", "initial"]
    assert commits[0].sha == site[2].commit_sha
    assert recent_commits(None, site[2]) == []


def test_the_indexed_commit_is_exact_to_the_line(site: Site) -> None:
    found = commit_changes(site[3], site[2], site[2].commit_sha[:10])
    assert found.exact and found.title.endswith("helper returns 2")
    assert [c.path for c in found.changes] == ["lib/util.py"]
    assert found.changes[0].ranges     # line ranges, not the whole file
    # Only the edited line counts: `apply_gate`, three lines below, is not marked.
    assert changed_by(site, found.changes) == ("lib/util.py::helper",)


def test_an_older_commit_counts_whole_files_and_says_so(site: Site) -> None:
    older = recent_commits(site[3], site[2])[1]
    found = commit_changes(site[3], site[2], older.sha)
    assert not found.exact and "counts whole" in found.note
    assert {c.path for c in found.changes} == set(REPO)
    assert all(c.ranges == () for c in found.changes)


@pytest.mark.parametrize("sha", ["--help", "HEAD", "abc", "0000000000", "a b"])
def test_a_commit_id_that_is_not_one_is_refused(site: Site, sha: str) -> None:
    with pytest.raises(ChangeError):
        commit_changes(site[3], site[2], sha)


def test_uncommitted_changes_use_the_snapshots_line_numbers(site: Site) -> None:
    """Three new lines at the top push `apply_gate` down in the working tree. The diff
    is read in reverse, so the change still lands on `apply_gate` and not on `helper`."""
    util = site[3] / "lib" / "util.py"
    text = util.read_text(encoding="utf-8")
    util.write_text("# a\n# b\n# c\n" + text.replace("return 1", "return 3"), encoding="utf-8")
    found = worktree_changes(site[3], site[2])
    assert found.exact
    changed = changed_by(site, found.changes)
    assert "lib/util.py::apply_gate" in changed
    assert "lib/util.py::helper" not in changed


def test_uncommitted_changes_are_refused_once_the_checkout_moves_on(site: Site) -> None:
    assert at_snapshot(site[3], site[2])
    (site[3] / "new.py").write_text("x = 1\n", encoding="utf-8")
    run_git(site[3], "add", "new.py")
    run_git(site[3], "commit", "-q", "-m", "later")
    assert not at_snapshot(site[3], site[2])
    with pytest.raises(ChangeError):
        worktree_changes(site[3], site[2])
    # The commits offered still stop at the indexed one.
    assert recent_commits(site[3], site[2])[0].sha == site[2].commit_sha


def test_a_pasted_diff_needs_a_file_header() -> None:
    assert [c.path for c in pasted_changes(DIFF).changes] == ["lib/util.py"]
    for text in ("", "just some words\n"):
        with pytest.raises(ChangeError):
            pasted_changes(text)


# The facts on the page


def test_impact_view_separates_tests_to_run_from_other_files(site: Site) -> None:
    db_path, _, snapshot, _ = site
    with GraphStore(db_path) as store:
        loaded = load_snapshot(store, snapshot)
        engine = ImpactEngine(store, snapshot.id)
        result = engine.impact([Change("lib/util.py", symbol_keys=("lib/util.py::helper",))])
        view = impact_view(loaded, result, engine.config.test_threshold, all_test_files(engine))
    assert [t["path"] for t in view["tests"]] == ["tests/test_util.py"]
    assert view["test_files"] == 2 and view["skipped_share"] == 0.5
    assert [f["path"] for f in view["files"]] == ["app/service.py"]
    save = next(s for s in view["files"][0]["symbols"] if s["name"]["label"] == "Service.save")
    hops = save["why"]["hops"]
    assert [h["label"] for h in hops] == ["helper", "Service.save"]
    assert hops[1]["kind"] == "calls" and hops[1]["node"] is not None
    assert [x["label"] for x in view["changed"]] == ["helper"]


# Pages


def test_the_page_offers_commits_a_diff_box_and_uncommitted_changes(
    site: Site, http: tuple[TestClient, str]
) -> None:
    client, url = http
    page = client.get(url)
    assert page.status_code == 200
    assert f"impact?commit={site[2].commit_sha}" in page.text
    assert "impact?change=worktree" in page.text and "<textarea" in page.text


def test_a_commit_shows_tests_to_run_and_files_reached(
    site: Site, http: tuple[TestClient, str]
) -> None:
    client, url = http
    page = client.get(url, params={"commit": site[2].commit_sha})
    assert page.status_code == 200
    assert "tests/test_util.py" in page.text and "app/service.py" in page.text
    assert "tests/test_other.py" not in page.text
    assert "50% can be skipped" in page.text


def test_a_file_a_symbol_and_the_working_tree(site: Site, http: tuple[TestClient, str]) -> None:
    client, url = http
    assert "Service.save" in client.get(url, params={"symbol": "lib/util.py::helper"}).text
    assert "tests/test_util.py" in client.get(url, params={"file": "lib/util.py"}).text
    assert client.get(url, params={"change": "worktree"}).status_code == 200
    assert client.get(url, params={"symbol": "lib/util.py::nope"}).status_code == 404
    assert client.get(url, params={"file": "../secret.py"}).status_code == 404


def test_a_bad_commit_id_comes_back_as_the_form_with_the_reason(
    http: tuple[TestClient, str]
) -> None:
    client, url = http
    page = client.get(url, params={"commit": "--help"})
    assert page.status_code == 400
    assert "is not a commit id" in page.text and "<textarea" in page.text


def test_a_pasted_diff_is_posted(http: tuple[TestClient, str]) -> None:
    client, url = http
    page = client.post(url, data={"diff": DIFF})
    assert page.status_code == 200 and "tests/test_util.py" in page.text
    assert client.post(url, data={"diff": "not a diff"}).status_code == 400
    assert client.post(url, data={"diff": "x" * (MAX_DIFF_BYTES + 1)}).status_code == 413


def test_file_and_symbol_pages_link_to_impact(site: Site, http: tuple[TestClient, str]) -> None:
    client, url = http
    base = url.removesuffix("/impact")
    file = client.get(f"{base}/file", params={"path": "lib/util.py"})
    assert "impact?file=lib/util.py" in file.text
    symbol = client.get(f"{base}/symbol", params={"key": "lib/util.py::helper"})
    assert "impact?symbol=lib/util.py%3A%3Ahelper" in symbol.text


def test_text_from_a_diff_is_shown_as_text(http: tuple[TestClient, str]) -> None:
    client, url = http
    nasty = DIFF.replace("lib/util.py", "<script>x</script>.py")
    page = client.post(url, data={"diff": nasty})
    assert page.status_code == 200
    assert "<script>x" not in page.text and "&lt;script&gt;" in page.text
