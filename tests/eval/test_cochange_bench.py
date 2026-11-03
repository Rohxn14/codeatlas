"""The co-change benchmark on a repository with scripted commits and known answers."""

from pathlib import Path

import pytest

from eval.cochange.benchmark import Query, build_queries, evaluate
from eval.cochange.predictors import CoChangePredictor, SameFolderPredictor
from tests.conftest import git


def commit(root: Path, files: list[str], n: int) -> str:
    for rel in files:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# change {n}\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", f"c{n}")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def scripted(tmp_path) -> tuple[Path, str]:
    """pkg/a.py and pkg/b.py change together three times; the held-out commit adds other/x.py."""
    root = tmp_path / "scripted"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    commit(root, ["pkg/old.py", "other/y.py"], 0)
    for n in (1, 2, 3):
        commit(root, ["pkg/a.py", "pkg/b.py"], n)
    return root, commit(root, ["pkg/a.py", "pkg/b.py", "other/x.py"], 4)


def test_queries_are_built_from_the_held_out_commit(scripted):
    root, held_out = scripted
    queries = [q for q in build_queries(root, 100) if q.commit == held_out]
    assert {q.file for q in queries} == {"pkg/a.py", "pkg/b.py", "other/x.py"}
    a = next(q for q in queries if q.file == "pkg/a.py")
    assert a.truth == {"pkg/b.py", "other/x.py"}
    assert a.language == "python"


def test_predictors_see_only_earlier_history(scripted):
    root, held_out = scripted
    rev = f"{held_out}^"
    assert CoChangePredictor().predict(root, rev, "pkg/a.py", 5) == ["pkg/b.py"]
    assert SameFolderPredictor().predict(root, rev, "pkg/a.py", 5) == ["pkg/b.py", "pkg/old.py"]
    assert CoChangePredictor().predict(root, rev, "other/x.py", 5) == []


def test_scores_for_both_predictors(scripted):
    root, held_out = scripted
    truth = frozenset({"pkg/b.py", "other/x.py"})
    queries = [
        Query(held_out, "pkg/a.py", "python", truth),
        Query(held_out, "other/x.py", "python", frozenset({"pkg/a.py", "pkg/b.py"})),
    ]
    co = evaluate(root, queries, CoChangePredictor())["overall"]
    assert co["precision@5"] == 1.0  # the one prediction made was right
    assert co["recall@5"] == 0.25  # (1/2 + 0) / 2 queries
    assert co["no_prediction_share"] == 0.5
    base = evaluate(root, queries, SameFolderPredictor())["overall"]
    assert base["precision@5"] == 0.25  # query 1: b.py hit, old.py miss; query 2: y.py miss
    assert base["recall@5"] == 0.25
    assert base["no_prediction_share"] == 0.0  # the baseline always has a folder to guess from
