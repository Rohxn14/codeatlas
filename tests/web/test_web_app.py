"""The local web app: routes, the overview facts, and untrusted text staying text."""

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.cli import main
from codeatlas.config import Config
from codeatlas.indexer.pipeline import index_repository
from codeatlas.models import Edge, EdgeKind, FileRecord, Resolution, Snapshot, Tier
from codeatlas.store import GraphStore
from codeatlas.web import create_app, find_snapshot, snapshot_slug
from codeatlas.web.confidence import CERTAIN, GUESS, LIKELY, level
from codeatlas.web.data import load_snapshot
from codeatlas.web.overview import build_overview, share, tier_shares, trust_rows, trust_total

FILES = {
    "app/service.py": "class Service:\n    def save(self):\n        helper()\n        print(1)\n",
    "lib/util.py": "def helper():\n    pass\n",
    "app/broken.py": "def broken(:\n",
    "README.md": "# demo\n",
}


@pytest.fixture
def indexed(make_repo: Callable[..., Path], tmp_path: Path) -> tuple[Path, Config, str]:
    """A small repository indexed into a database: (database, config, snapshot id)."""
    config = Config(data_dir=(tmp_path / "data").as_posix())
    db_path = tmp_path / "data" / "codeatlas.db"
    report = index_repository(str(make_repo(FILES, name="demo")), config, db_path)
    return db_path, config, report.snapshot["id"]


def edge(kind: EdgeKind, confidence: float) -> Edge:
    return Edge("a", "b", kind, confidence, Resolution.DIRECT)


# Confidence levels


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [(1.0, CERTAIN), (0.9, CERTAIN), (0.89, LIKELY), (0.5, LIKELY), (0.49, GUESS), (0.1, GUESS)],
)
def test_level_boundaries(confidence: float, expected: str) -> None:
    assert level(confidence) == expected


# Overview facts


def test_share_of_nothing_is_none() -> None:
    assert share(0, 0) is None
    assert share(1, 4) == 0.25


def test_tier_shares_always_lists_three_tiers() -> None:
    files = [FileRecord("a.py", "python", Tier.DEEP, "x", 1)]
    rows = tier_shares(files)
    assert [r["tier"] for r in rows] == ["deep", "structural", "text"]
    assert [r["files"] for r in rows] == [1, 0, 0]


def test_trust_leaves_containment_out_of_the_meter() -> None:
    edges = [edge(EdgeKind.CONTAINS, 1.0), edge(EdgeKind.CALLS, 1.0), edge(EdgeKind.CALLS, 0.2)]
    total = trust_total(edges)
    assert total["total"] == 2
    assert {row["level"]: row["count"] for row in total["levels"]} == {
        CERTAIN: 1, LIKELY: 0, GUESS: 1,
    }
    rows = {row["kind"]: row for row in trust_rows(edges)}
    assert rows["contains"]["by_construction"] is True
    assert rows["calls"]["levels"] == {CERTAIN: 1, LIKELY: 0, GUESS: 1}


def test_overview_counts_match_the_store(indexed: tuple[Path, Config, str]) -> None:
    db_path, _, snapshot_id = indexed
    with GraphStore(db_path) as store:
        snapshot = store.get_snapshot(snapshot_id)
        assert snapshot is not None
        overview = build_overview(load_snapshot(store, snapshot))
        assert overview["totals"]["files"] == len(store.files(snapshot_id))
        assert overview["totals"]["edges"] == len(store.edges(snapshot_id))
        calls = store.raw_calls(snapshot_id)
    assert overview["calls"]["total"] == len(calls)
    assert overview["calls"]["resolved"] == sum(1 for _, done in calls if done)
    assert overview["problems"]["files_with_errors"]["total"] == 1
    assert overview["problems"]["report_missing"] is True  # no report was passed in


# Slugs


def test_slug_round_trip_for_an_id_with_a_slash(tmp_path: Path) -> None:
    assert snapshot_slug("pallets/itsdangerous@672971d66a2e") == "pallets~itsdangerous@672971d66a2e"
    with GraphStore(tmp_path / "empty.db") as store:
        assert find_snapshot(store, "pallets~itsdangerous@672971d66a2e") is None


# Routes


def test_home_redirects_to_the_only_snapshot(indexed: tuple[Path, Config, str]) -> None:
    db_path, config, snapshot_id = indexed
    client = TestClient(create_app(db_path, config), follow_redirects=False)
    response = client.get("/")
    assert response.status_code == 307
    assert response.headers["location"] == f"/s/{snapshot_slug(snapshot_id)}/"


def test_coverage_page_shows_counts_and_gaps(indexed: tuple[Path, Config, str]) -> None:
    db_path, config, snapshot_id = indexed
    client = TestClient(create_app(db_path, config))
    page = client.get(f"/s/{snapshot_slug(snapshot_id)}/coverage")
    assert page.status_code == 200
    assert "How much of demo is on the map" in page.text
    assert "What could not be analysed" in page.text
    assert "app/broken.py" in page.text  # the file with a parse error is named
    assert "Resolved does not mean correct" in page.text


def test_snapshot_list_and_static_file(indexed: tuple[Path, Config, str]) -> None:
    db_path, config, snapshot_id = indexed
    client = TestClient(create_app(db_path, config))
    listing = client.get("/snapshots")
    assert listing.status_code == 200
    assert f'href="/s/{snapshot_slug(snapshot_id)}/"' in listing.text
    assert client.get("/static/app.css").status_code == 200


def test_unknown_snapshot_and_unknown_address_are_404_pages(
    indexed: tuple[Path, Config, str]
) -> None:
    client = TestClient(create_app(indexed[0], indexed[1]))
    for address in ("/s/nope@000/", "/no/such/page"):
        page = client.get(address)
        assert page.status_code == 404
        assert "Nothing at this address" in page.text


def test_missing_database_is_a_503_page(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "absent.db", Config()))
    page = client.get("/")
    assert page.status_code == 503
    assert "codeatlas index" in page.text
    assert not (tmp_path / "absent.db").exists()  # asking must not create a database


def test_repository_text_is_escaped(tmp_path: Path) -> None:
    """A repository named like a tag must reach the page as text, never as markup.

    Written to the store directly: Windows does not allow `<` in a folder name.
    """
    db_path = tmp_path / "codeatlas.db"
    snapshot = Snapshot("x@abc", "b<img src=x>", "abc", "2026-11-15T00:00:00Z", "0", "<b>src</b>")
    with GraphStore(db_path) as store:
        store.create_snapshot(snapshot)
    client = TestClient(create_app(db_path, Config(data_dir=tmp_path.as_posix())))
    for address in ("/s/x@abc/", "/s/x@abc/coverage", "/snapshots"):
        page = client.get(address)
        assert page.status_code == 200
        assert "<img" not in page.text and "<b>src" not in page.text
        assert "&lt;img" in page.text


# The command


def test_serve_without_a_database_says_what_to_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    toml = tmp_path / "ct.toml"
    toml.write_text(f'[paths]\ndata_dir = "{(tmp_path / "data").as_posix()}"\n', encoding="utf-8")
    assert main(["serve", "--config", str(toml), "--no-open"]) == 2
    assert "codeatlas index" in capsys.readouterr().err


def test_many_requests_at_once_each_get_a_page(tmp_path: Path) -> None:
    """A SQLite connection belongs to the thread that opened it. Requests that arrive
    together run on different worker threads, so each must open and close its own."""
    from concurrent.futures import ThreadPoolExecutor

    config = Config(data_dir=(tmp_path / "data").as_posix())
    db_path = tmp_path / "data" / "codeatlas.db"
    db_path.parent.mkdir(parents=True)
    with GraphStore(db_path) as store:
        store.create_snapshot(Snapshot("demo@abc", "demo", "abc", "2026-11-16T00:00:00Z", "0", "x"))
    with TestClient(create_app(db_path, config)) as client:
        def get(_: int) -> int:
            return client.get("/s/demo@abc/search", params={"q": "anything"}).status_code

        with ThreadPoolExecutor(8) as pool:
            codes = list(pool.map(get, range(40)))
    assert codes == [200] * 40
