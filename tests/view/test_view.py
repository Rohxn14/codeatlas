"""The viewer's data and page, and the `index`, `view` and `export` commands."""

import json
import re
import webbrowser
from collections.abc import Callable
from pathlib import Path

import pytest

from codeatlas.cli import main
from codeatlas.config import Config
from codeatlas.indexer.pipeline import index_repository
from codeatlas.store import GraphStore
from codeatlas.view import build_view_data, render_html

FILES = {
    "app/service.py": "class Service:\n    def save(self):\n        helper()\n",
    "lib/util.py": "def helper():\n    pass\n",
    "app/broken.py": "def broken(:\n",
    "README.md": "# </script><b>x</b>\n",
}


@pytest.fixture
def setup(make_repo: Callable[..., Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def no_browser(*_: object, **__: object) -> bool:
        raise AssertionError("a test opened a browser")

    monkeypatch.setattr(webbrowser, "open", no_browser)
    repo = make_repo(FILES, name="demo")
    toml = tmp_path / "ct.toml"
    data_dir = (tmp_path / "data").as_posix()
    toml.write_text(f'[paths]\ndata_dir = "{data_dir}"\n', encoding="utf-8")
    return repo, toml, tmp_path / "data" / "codeatlas.db"


def embedded(html: str) -> dict:
    match = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S)
    assert match
    return json.loads(match.group(1))


def test_index_command_prints_summary_and_next_step(setup, capsys) -> None:
    repo, toml, _ = setup
    assert main(["index", str(repo), "--config", str(toml)]) == 0
    out = capsys.readouterr().out
    assert "Edges:" in out and "Raw calls:" in out and "app/broken.py" in out
    assert "Next: codeatlas view" in out


def test_export_matches_contract_section_8(setup) -> None:
    repo, toml, db = setup
    out = db.parent / "graph.json"
    assert main(["index", str(repo), "--config", str(toml)]) == 0
    assert main(["export", "--config", str(toml), "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) == {"snapshot", "nodes", "edges"}
    assert set(data["snapshot"]) == {
        "id", "repo", "commit_sha", "indexed_at", "indexer_version", "source", "limits_hit"
    }
    assert set(data["nodes"][0]) == {"key", "kind", "language", "path", "span"}
    assert set(data["edges"][0]) == {
        "src_key", "dst_key", "kind", "confidence", "resolution", "line"
    }


def test_view_writes_a_page_naming_the_snapshot(setup, capsys) -> None:
    repo, toml, db = setup
    out = db.parent / "v.html"
    main(["index", str(repo), "--config", str(toml)])
    assert main(["view", "--config", str(toml), "--no-open", "--out", str(out)]) == 0
    html = out.read_text(encoding="utf-8")
    data = embedded(html)
    sid = data["snapshot"]["id"]
    assert sid.startswith("demo@") and sid in html
    assert "</script><b>" not in html  # repository text cannot close the data tag
    assert data["problems"]["files_with_errors"][0]["path"] == "app/broken.py"
    assert {f["path"] for f in data["files"]} == set(FILES)


def test_focus_limits_the_embedded_files(setup) -> None:
    repo, toml, db = setup
    config = Config(data_dir=str(db.parent))
    report = index_repository(str(repo), config, db)
    with GraphStore(db) as store:
        data = build_view_data(store, report.snapshot["id"], None, focus="app")
    assert {f["path"] for f in data["files"]} == {"app/service.py", "app/broken.py"}
    assert data["omitted"]["files"] == 2
    assert all(n["path"].startswith("app/") or not n["path"] for n in data["nodes"])
    assert "--focus" in render_html(data)


def test_size_cap_is_reported_on_the_page(setup) -> None:
    repo, _, db = setup
    config = Config(data_dir=str(db.parent))
    report = index_repository(str(repo), config, db)
    with GraphStore(db) as store:
        data = build_view_data(store, report.snapshot["id"], None, max_nodes=4)
    omitted = data["omitted"]
    assert omitted["capped"] and omitted["nodes"] > 0 and omitted["files"] > 0
    assert len(data["nodes"]) <= 4
    html = render_html(data)
    assert embedded(html)["omitted"]["max_nodes"] == 4 and "the page holds at most" in html


def test_commands_without_a_database_fail_clearly(tmp_path: Path, capsys) -> None:
    toml = tmp_path / "ct.toml"
    toml.write_text(f'[paths]\ndata_dir = "{(tmp_path / "none").as_posix()}"\n', encoding="utf-8")
    assert main(["view", "--config", str(toml), "--no-open"]) == 2
    assert "codeatlas index" in capsys.readouterr().err
