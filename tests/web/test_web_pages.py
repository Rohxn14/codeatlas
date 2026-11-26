"""The file, symbol and search pages, and reading source from the checkout."""

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.config import Config
from codeatlas.indexer.pipeline import index_repository
from codeatlas.models import Snapshot
from codeatlas.store import GraphStore
from codeatlas.web import create_app, snapshot_slug
from codeatlas.web.data import Loaded, load_snapshot
from codeatlas.web.diagram import crumbs
from codeatlas.web.pages import file_page, search, symbol_page
from codeatlas.web.source import checkout_root, read_lines

REPO = {
    "app/service.py": (
        "from lib.util import helper\n\n\n"
        "class Service:\n"
        '    """Saves things."""\n\n'
        "    def save(self):\n"
        "        helper()\n"
        "        unknown_thing()\n"
    ),
    "lib/util.py": "def helper():\n    pass\n\n\ndef apply_gate():\n    helper()\n",
    "notes.txt": "<b>hello</b>\n",
}


@pytest.fixture
def site(make_repo: Callable[..., Path], tmp_path: Path) -> tuple[Path, Config, Snapshot, Path]:
    """A small indexed repository: (database, config, snapshot, checkout folder)."""
    config = Config(data_dir=(tmp_path / "data").as_posix())
    db_path = tmp_path / "data" / "codeatlas.db"
    repo = make_repo(REPO, name="demo")
    report = index_repository(str(repo), config, db_path)
    with GraphStore(db_path) as store:
        snapshot = store.get_snapshot(report.snapshot["id"])
    assert snapshot is not None
    return db_path, config, snapshot, repo


@pytest.fixture
def loaded(site: tuple[Path, Config, Snapshot, Path]) -> Loaded:
    with GraphStore(site[0]) as store:
        return load_snapshot(store, site[2])


@pytest.fixture
def http(site: tuple[Path, Config, Snapshot, Path]) -> tuple[TestClient, str]:
    return TestClient(create_app(site[0], site[1])), f"/s/{snapshot_slug(site[2].id)}"


# Facts


def test_file_page_lists_symbols_and_neighbours(loaded: Loaded) -> None:
    facts = file_page(loaded, "app/service.py")
    assert facts is not None
    assert [(s["node"].name, s["depth"]) for s in facts["symbols"]] == [("Service", 0), ("save", 1)]
    assert [row["path"] for row in facts["uses"]] == ["lib/util.py"]
    assert facts["uses"][0]["level"] == "certain"
    assert facts["used_by"] == []
    assert facts["calls"] == {"total": 2, "resolved": 1}   # helper() resolved, unknown_thing() not
    assert facts["starts"][4].name == "Service"


def test_file_page_the_other_way_round(loaded: Loaded) -> None:
    facts = file_page(loaded, "lib/util.py")
    assert facts is not None
    assert [row["path"] for row in facts["used_by"]] == ["app/service.py"]


def test_file_page_of_an_unknown_file_is_none(loaded: Loaded) -> None:
    assert file_page(loaded, "nope.py") is None


def test_symbol_page_shows_both_directions_and_calls_without_an_edge(loaded: Loaded) -> None:
    facts = symbol_page(loaded, "app/service.py::Service.save")
    assert facts is not None
    assert facts["owner"].name == "Service"
    assert [row["other"].name for row in facts["uses"]["rows"]] == ["helper"]
    assert [call.callee_text for call in facts["unresolved"]] == ["unknown_thing"]
    helper = symbol_page(loaded, "lib/util.py::helper")
    assert helper is not None
    users = {row["other"].name for row in helper["used_by"]["rows"]}
    assert {"save", "apply_gate"} <= users
    assert helper["used_by"]["levels"]["certain"] == helper["used_by"]["total"]


def test_symbol_page_lists_members_and_unknown_key_is_none(loaded: Loaded) -> None:
    facts = symbol_page(loaded, "app/service.py::Service")
    assert facts is not None
    assert [m.name for m in facts["members"]] == ["save"]
    assert symbol_page(loaded, "app/service.py::Nope") is None


def test_search_adds_names_that_only_contain_the_text(loaded: Loaded) -> None:
    # Full-text search matches whole words, so it returns nothing for "gate".
    hits = search(loaded, [], "gate")
    assert [n.name for n in hits] == ["apply_gate"]
    assert search(loaded, [], "service")[0].path == "app/service.py"


def test_search_keeps_ranked_hits_first_and_never_repeats_one(loaded: Loaded) -> None:
    helper = loaded.by_key["lib/util.py::helper"]
    hits = search(loaded, [helper], "help")
    assert hits[0] is helper
    assert sum(1 for n in hits if n.id == helper.id) == 1


def test_crumbs_mark_the_file_at_the_end() -> None:
    assert crumbs("app/service.py") == [
        {"name": "app", "focus": "app/"}, {"name": "service.py", "focus": ""},
    ]


# Source


def test_read_lines_stays_inside_the_checkout(site: tuple[Path, Config, Snapshot, Path]) -> None:
    _, config, snapshot, repo = site
    root = checkout_root(snapshot, config)
    assert root is not None and root.resolve() == repo.resolve()
    lines, why_not = read_lines(root, "lib/util.py")
    assert lines is not None and lines[0] == "def helper():" and why_not == ""
    (repo.parent / "secret.txt").write_text("key\n", encoding="utf-8")
    outside, why_not = read_lines(root, "../secret.txt")
    assert outside is None and "not in the checkout" in why_not


def test_read_lines_without_a_checkout_says_why() -> None:
    lines, why_not = read_lines(None, "a.py")
    assert lines is None and "no longer on disk" in why_not


def test_checkout_root_of_a_folder_that_is_gone(tmp_path: Path) -> None:
    gone = Snapshot("x@abc", "x", "abc", "2026-11-16T00:00:00Z", "0", str(tmp_path / "gone"))
    assert checkout_root(gone, Config(data_dir=tmp_path.as_posix())) is None


# Pages


def test_file_page_shows_source_and_links(http: tuple[TestClient, str]) -> None:
    client, base = http
    page = client.get(f"{base}/file", params={"path": "app/service.py"})
    assert page.status_code == 200
    assert 'id="L7"' in page.text and "def save(self):" in page.text
    assert "symbol?key=app/service.py%3A%3AService.save" in page.text
    assert "file?path=lib/util.py" in page.text


def test_text_file_is_shown_as_text_never_as_markup(http: tuple[TestClient, str]) -> None:
    client, base = http
    page = client.get(f"{base}/file", params={"path": "notes.txt"})
    assert page.status_code == 200
    assert "text tier" in page.text
    assert "<b>hello</b>" not in page.text and "&lt;b&gt;hello&lt;/b&gt;" in page.text


def test_file_outside_the_snapshot_is_a_404(http: tuple[TestClient, str]) -> None:
    client, base = http
    for path in ("nope.py", "../secret.txt"):
        assert client.get(f"{base}/file", params={"path": path}).status_code == 404


def test_symbol_page_and_unknown_symbol(http: tuple[TestClient, str]) -> None:
    client, base = http
    page = client.get(f"{base}/symbol", params={"key": "lib/util.py::helper"})
    assert page.status_code == 200
    assert "Used by" in page.text and "Service.save" in page.text
    assert "def helper():" in page.text
    assert client.get(f"{base}/symbol", params={"key": "lib/util.py::nope"}).status_code == 404


def test_search_page_finds_misses_and_waits(http: tuple[TestClient, str]) -> None:
    client, base = http
    found = client.get(f"{base}/search", params={"q": "helper"})
    assert found.status_code == 200 and "symbol?key=lib/util.py%3A%3Ahelper" in found.text
    missed = client.get(f"{base}/search", params={"q": "zzzqqq"})
    assert "Nothing matches" in missed.text
    assert client.get(f"{base}/search").status_code == 200


def test_a_file_changed_after_indexing_is_shown_as_it_was_indexed(
    site: tuple[Path, Config, Snapshot, Path], http: tuple[TestClient, str]
) -> None:
    """The map's line numbers belong to the indexed commit: lines read from a checkout that
    moved on would sit at the wrong numbers. Git still has the indexed version."""
    client, base = http
    util = site[3] / "lib" / "util.py"
    util.write_text("# a new first line\n" + util.read_text(encoding="utf-8"), encoding="utf-8")
    page = client.get(f"{base}/file", params={"path": "lib/util.py"}).text
    assert "a new first line" not in page and "def helper():" in page
    assert "As indexed, at commit" in page
    symbol = client.get(f"{base}/symbol", params={"key": "lib/util.py::apply_gate"}).text
    assert "def apply_gate():" in symbol and "a new first line" not in symbol
    util.unlink()  # gone from the checkout, still in the commit
    assert "def helper():" in client.get(f"{base}/file", params={"path": "lib/util.py"}).text


def test_a_changed_file_that_git_cannot_give_back_is_shown_with_a_notice(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "plain"  # not a git repository: nothing to read the old version from
    (folder / "lib").mkdir(parents=True)
    util = folder / "lib" / "util.py"
    util.write_text(REPO["lib/util.py"], encoding="utf-8")
    config = Config(data_dir=(tmp_path / "data").as_posix())
    db_path = tmp_path / "data" / "codeatlas.db"
    sid = index_repository(str(folder), config, db_path).snapshot["id"]
    client, base = TestClient(create_app(db_path, config)), f"/s/{snapshot_slug(sid)}"
    util.write_text("# changed\n" + REPO["lib/util.py"], encoding="utf-8")
    page = client.get(f"{base}/file", params={"path": "lib/util.py"}).text
    assert "# changed" in page and "has changed since it was indexed" in page
    util.unlink()
    page = client.get(f"{base}/file", params={"path": "lib/util.py"})
    assert page.status_code == 200 and "not in the checkout" in page.text
    assert "apply_gate" in page.text  # the outline comes from the map, not the disk
