import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from conftest import git
from test_manifests import SAMPLES, records

from codeatlas.config import Config
from codeatlas.indexer.adapter import RepoAnalyzer
from codeatlas.models import Edge, Node
from codeatlas.repo import (
    CoChangeAnalyzer,
    ManifestAnalyzer,
    TestConventionsAnalyzer,
    default_analyzers,
    summarize,
)


def test_default_analyzers_follow_the_contract_and_config() -> None:
    analyzers = default_analyzers(replace(Config(), max_history_commits=50))
    assert [a.name for a in analyzers] == [
        "manifests", "test_conventions", "cochange", "references"]
    assert all(isinstance(a, RepoAnalyzer) for a in analyzers)
    assert isinstance(analyzers[0], ManifestAnalyzer)
    assert isinstance(analyzers[1], TestConventionsAnalyzer)
    cochange = analyzers[2]
    assert isinstance(cochange, CoChangeAnalyzer) and cochange.max_commits == 50
    default_cochange = default_analyzers()[2]
    assert isinstance(default_cochange, CoChangeAnalyzer)
    assert default_cochange.max_commits == Config().max_history_commits


def test_summary_of_a_whole_run(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    source = tmp_path / "src-copy"
    shutil.copytree(SAMPLES / "maven", source)
    files = {p.relative_to(source).as_posix(): p.read_text(encoding="utf-8")
             for p in source.rglob("*") if p.is_file()}
    root = make_repo(files)
    for _ in range(3):
        for rel in ("core/src/main/java/com/acme/core/Money.java",
                    "core/src/test/java/com/acme/core/MoneyTest.java"):
            text = (root / rel).read_text(encoding="utf-8")
            (root / rel).write_text(text + "// more\n", encoding="utf-8")
        git(root, "commit", "-qam", "change")
    found = [r for r in records(root) if not r.path.startswith(".git/")]
    analyzers = default_analyzers()
    nodes: list[Node] = []
    edges: list[Edge] = []
    for analyzer in analyzers:
        more_nodes, more_edges = analyzer.analyze(root, found, "maven@0123456789ab")
        nodes += more_nodes
        edges += more_edges
    summary = summarize(found, nodes, edges, analyzers)
    assert summary["packages"] == {
        "total": 3,
        "real": 3,
        "by_role": {"package": 3},
        "by_ecosystem": {"maven": 3},
        "implicit": False,
        "internal_dependencies": 1,
        "warnings": [],
    }
    assert summary["tests"] == {
        "test_files": 1, "paired": 1, "pairing_rate": 1.0, "ambiguous": 0, "unpaired": [],
    }
    cochange = summary["cochange"]
    assert isinstance(cochange, dict)
    assert cochange["edges"] == 2 and cochange["files_with_edges"] == 2
    assert cochange["status"] == "ok"
    assert cochange["commits_read"] == 4 and cochange["commits_analysed"] == 4
    assert cochange["files_removed"] == {
        "vendored": 0, "lockfile": 0, "generated": 0, "not_in_snapshot": 0,
    }
    languages = summary["languages"]
    assert isinstance(languages, list)
    assert {(r["language"], r["files"]) for r in languages} == {("java", 3), ("xml", 3)}


def test_summary_without_analyzer_reports() -> None:
    root = SAMPLES / "none"
    found = records(root)
    nodes, edges = ManifestAnalyzer().analyze(root, found, "none@0123456789ab")
    summary = summarize(found, nodes, edges)
    packages, tests = summary["packages"], summary["tests"]
    assert isinstance(packages, dict) and isinstance(tests, dict)
    assert packages["implicit"] is True
    assert tests["pairing_rate"] is None
    assert summary["cochange"] == {"edges": 0, "files_with_edges": 0}
