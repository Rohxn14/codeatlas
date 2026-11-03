"""The engine as a co-change predictor, and an end-to-end run through the real indexer."""

from __future__ import annotations

from pathlib import Path

from codeatlas.impact import Change, impact
from codeatlas.indexer.pipeline import build_graph
from codeatlas.store import GraphStore
from eval.cochange.predictors import ImpactPredictor
from tests.conftest import git


def commit(root: Path, files: dict[str, str], n: int) -> str:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", f"c{n}")
    return git(root, "rev-parse", "HEAD")


def make_project(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    lib = "def save(x):\n    return x\n"
    app = "from lib import save\n\ndef run(x):\n    return save(x)\n"
    test = "from app import run\n\ndef test_run():\n    assert run(1) == 1\n"
    commit(root, {"lib.py": lib, "app.py": app, "test_app.py": test}, 0)
    for n in (1, 2, 3):  # lib.py and notes.py change together
        commit(root, {"lib.py": lib + f"# {n}\n", "notes.py": f"# {n}\n"}, n)
    held_out = commit(root, {"lib.py": lib + "# 4\n", "notes.py": "# 4\n"}, 4)
    return root, held_out


def test_end_to_end_on_a_real_index(tmp_path):
    root, _ = make_project(tmp_path)
    store = GraphStore(tmp_path / "i.db")
    built = build_graph(str(root), store)
    result = impact(store, built.snapshot_id, [Change("lib.py", ((1, 2),))])
    by_key = {t.key: t for t in result.targets}
    assert "app.py::run" in by_key
    assert [h.kind for h in by_key["app.py::run"].evidence[0].path[1:]] == ["calls"]
    assert "test_app.py" in [p.path for p in result.test_files()]
    store.close()


def test_predictor_uses_history_up_to_the_held_out_commit(tmp_path):
    root, held_out = make_project(tmp_path)
    store = GraphStore(tmp_path / "p.db")
    built = build_graph(str(root), store)
    predictor = ImpactPredictor(store, built.snapshot_id)
    ranked = predictor.predict(root, f"{held_out}^", "lib.py", 5)
    assert "app.py" in ranked  # through the call graph
    assert "notes.py" in ranked  # through history that ends before the held-out commit
    assert "lib.py" not in ranked
    assert predictor.predict(root, f"{held_out}^", "nothing.py", 5) == []
    store.close()
