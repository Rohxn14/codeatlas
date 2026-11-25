"""index_repository: the report matches the store, repeats reuse it, force rebuilds."""

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from codeatlas.config import Config
from codeatlas.indexer.pipeline import index_repository
from codeatlas.indexer.pipeline.index import SECONDS_STEPS, load_report, report_path
from codeatlas.store import GraphStore

FILES = {
    "app/service.py": "class Service:\n    def save(self):\n        helper()\n",
    "app/broken.py": "def ok():\n    pass\n\ndef broken(:\n",
    "main.go": "package main\n\nfunc main() {}\n",
    "README.md": "# demo\n",
}
FIELDS = {"snapshot", "seconds", "files", "nodes", "edges", "raw_calls", "problems", "repo_layer",
          "embeddings"}


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(data_dir=str(tmp_path / "data"))


@pytest.fixture
def repo(make_repo: Callable[..., Path]) -> Path:
    return make_repo(FILES, name="demo")


def test_report_counts_match_the_store(repo: Path, config: Config, tmp_path: Path) -> None:
    db = tmp_path / "data" / "codeatlas.db"
    report = index_repository(str(repo), config, db)
    with GraphStore(db) as store:
        sid = report.snapshot["id"]
        assert report.nodes["total"] == len(store.nodes(sid))
        assert report.edges["total"] == len(store.edges(sid))
        assert report.raw_calls["total"] == len(store.raw_calls(sid))
        assert report.files["total"] == len(store.files(sid)) == len(FILES)
    assert sum(report.edges["by_kind"].values()) == report.edges["total"]
    assert sum(report.nodes["by_kind"].values()) == report.nodes["total"]
    assert report.files["by_language"]["python"] == 2
    assert [p["path"] for p in report.problems["files_with_errors"]] == ["app/broken.py"]
    calls = report.raw_calls
    assert calls["resolved"] + calls["unresolved"] == calls["total"]
    assert set(report.seconds) == set(SECONDS_STEPS)


def test_report_is_saved_where_the_explainer_says(repo: Path, config: Config) -> None:
    db = Path(config.data_dir) / "codeatlas.db"
    report = index_repository(str(repo), config, db)
    sid = report.snapshot["id"]
    path = Path(config.data_dir) / "reports" / (sid.replace("@", "_").replace("/", "_") + ".json")
    assert path == report_path(config, sid) and path.exists()
    assert set(json.loads(path.read_text(encoding="utf-8"))) >= FIELDS


def test_second_run_returns_the_saved_report_and_force_rebuilds(
    repo: Path, config: Config
) -> None:
    db = Path(config.data_dir) / "codeatlas.db"
    first = index_repository(str(repo), config, db)
    path = report_path(config, first.snapshot["id"])
    stamp = path.stat().st_mtime_ns
    again = index_repository(str(repo), config, db)
    assert again.to_dict() == first.to_dict() and path.stat().st_mtime_ns == stamp
    forced = index_repository(str(repo), config, db, force=True)
    assert forced.nodes == first.nodes and path.stat().st_mtime_ns >= stamp
    assert forced.snapshot["indexed_at"] >= first.snapshot["indexed_at"]


def test_a_deleted_report_is_recreated(repo: Path, config: Config) -> None:
    db = Path(config.data_dir) / "codeatlas.db"
    first = index_repository(str(repo), config, db)
    report_path(config, first.snapshot["id"]).unlink()
    assert load_report(config, first.snapshot["id"]) is None
    assert index_repository(str(repo), config, db).nodes == first.nodes
    assert load_report(config, first.snapshot["id"]) is not None


def test_force_really_rebuilds(repo: Path, config: Config, monkeypatch) -> None:
    from codeatlas.indexer.pipeline import index as index_module

    db = Path(config.data_dir) / "codeatlas.db"
    index_repository(str(repo), config, db)
    calls = []
    real = index_module.build_graph

    def spy(*args, **kwargs):
        calls.append(kwargs.get("replace_existing"))
        return real(*args, **kwargs)

    monkeypatch.setattr(index_module, "build_graph", spy)
    index_repository(str(repo), config, db, force=True)
    assert calls == [True]


def test_folders_discovery_did_not_enter_are_in_the_report(
    make_repo: Callable[..., Path], config: Config
) -> None:
    repo = make_repo({"src/a.py": "def a():\n    pass\n", "node_modules/x/i.js": "x = 1\n"},
                     name="withdeps")
    report = index_repository(str(repo), config, Path(config.data_dir) / "c.db")
    not_entered = report.files["not_entered"]
    assert not_entered["total"] == 1 and not_entered["paths"][0]["path"] == "node_modules"


class FakeEmbedder:
    """Two numbers per text, so no test loads a real model."""

    model = "fake-model"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def embed(self, texts: list[str]) -> np.ndarray:
        if self.error is not None:
            raise self.error
        return np.array([[len(t), 1.0] for t in texts], dtype=np.float32)


def test_an_embedder_gives_the_new_snapshot_its_vectors(repo: Path, config: Config,
                                                        tmp_path: Path) -> None:
    db = tmp_path / "data" / "codeatlas.db"
    seen: list[tuple[str, str]] = []
    report = index_repository(str(repo), config, db, embedder=FakeEmbedder(),
                              progress=lambda step, detail: seen.append((step, detail)))
    sid = report.snapshot["id"]
    with GraphStore(db) as store:
        ids, vectors = store.embeddings(sid, "fake-model")
    assert report.embeddings["model"] == "fake-model" and "seconds" in report.embeddings
    assert report.embeddings["symbols"] == len(ids) == len(vectors) > 0
    assert load_report(config, sid).embeddings == report.embeddings  # saved, not only returned
    embed = [detail for step, detail in seen if step == "embed"]
    assert embed == ["", f"0 of {len(ids)} symbols"]  # after every other step
    assert [step for step, _ in seen][-2:] == ["embed", "embed"]


def test_a_model_that_cannot_run_is_reported_and_the_index_stands(
    repo: Path, config: Config, tmp_path: Path,
) -> None:
    db = tmp_path / "data" / "codeatlas.db"
    report = index_repository(str(repo), config, db,
                              embedder=FakeEmbedder(OSError("no network")))
    assert report.embeddings == {"model": "fake-model", "error": "OSError: no network"}
    assert report.nodes["total"] > 0
    assert load_report(config, report.snapshot["id"]).embeddings == report.embeddings


def test_stopping_half_way_through_embedding_keeps_the_report(
    repo: Path, config: Config, tmp_path: Path,
) -> None:
    db = tmp_path / "data" / "codeatlas.db"

    class Stopped(FakeEmbedder):
        def embed(self, texts: list[str]) -> np.ndarray:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        index_repository(str(repo), config, db, embedder=Stopped())
    # The next run finds the snapshot and its report, so nothing is rebuilt.
    steps: list[str] = []
    again = index_repository(str(repo), config, db,
                             progress=lambda step, detail: steps.append(step))
    assert "save" not in steps and again.embeddings == {}


def test_a_report_saved_before_embeddings_existed_still_loads(
    repo: Path, config: Config, tmp_path: Path,
) -> None:
    db = tmp_path / "data" / "codeatlas.db"
    sid = index_repository(str(repo), config, db).snapshot["id"]
    path = report_path(config, sid)
    old = json.loads(path.read_text(encoding="utf-8"))
    del old["embeddings"]
    path.write_text(json.dumps(old), encoding="utf-8")
    assert load_report(config, sid).embeddings == {}  # None here would force a full rebuild
