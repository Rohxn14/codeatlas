"""The resolver: sample projects scored against hand labels, and the rules one by one."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from codeatlas.indexer.pipeline import build_graph
from codeatlas.indexer.structural import StructuralResolver
from codeatlas.indexer.structural.resolver import MAX_GUESSES
from codeatlas.models import Edge, EdgeKind, ParseResult, Resolution
from codeatlas.store import GraphStore
from eval.oracle.graph import load_graph, parse_graph
from eval.oracle.score import score
from tests.conftest import DATA
from tests.indexer.structural.helpers import (
    GO_INDEX_ATTRS,
    GO_PACKAGE_KEY,
    SNAPSHOT,
    FakeIndex,
    go_module,
    parse,
)

SAMPLES = DATA / "structural"


def scored(language: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        store = GraphStore(Path(tmp) / "sample.db")
        try:
            built = build_graph(str(SAMPLES / language), store)
            export = store.export_json(built.snapshot_id)
        finally:
            store.close()
    truth = load_graph(SAMPLES / language / "expected_graph.json")
    return score(parse_graph(export), truth)


def kind_scores(result: dict, kind: str) -> dict:
    return result["by_kind"][kind]


def test_go_sample_matches_the_hand_labels_exactly() -> None:
    result = scored("go")
    for kind in ("calls", "imports"):
        assert kind_scores(result, kind)["precision"] == 1.0
        assert kind_scores(result, kind)["recall"] == 1.0


def test_java_sample_finds_every_labelled_edge() -> None:
    result = scored("java")
    assert kind_scores(result, "calls")["recall"] == 1.0
    assert kind_scores(result, "imports")["precision"] == 1.0
    assert kind_scores(result, "imports")["recall"] == 1.0
    # The only wrong edge is the second `log` overload: arguments are not in a RawCall.
    assert kind_scores(result, "calls")["precision"] >= 0.85
    assert kind_scores(result, "calls")["fp"] == 1


def resolve(files: dict[str, str], packages: dict | None = None) -> list[Edge]:
    results: list[ParseResult] = []
    for path, text in files.items():
        parsed = parse(path, text)
        if path.endswith(".go"):
            parsed = go_module(parsed, GO_PACKAGE_KEY)
        results.append(parsed)
    index = FakeIndex(GO_INDEX_ATTRS if packages is None else packages)
    return StructuralResolver().resolve(results, index)  # type: ignore[arg-type]


def calls(edges: list[Edge]) -> list[tuple[str, str, float, Resolution]]:
    return [
        (e.src_id.split("/", 1)[1], e.dst_id.split("/", 1)[1], e.confidence, e.resolution)
        for e in edges
        if e.kind is EdgeKind.CALLS
    ]


def test_languages_are_every_structural_language_and_no_deep_one() -> None:
    languages = StructuralResolver.languages
    assert {"java", "go", "ruby", "rust"} <= languages
    assert not languages & {"python", "typescript", "tsx", "javascript"}


def test_name_guess_without_a_profile_is_capped_at_point_three() -> None:
    edges = resolve({
        "a.rb": "class A\n  def go\n    helper()\n  end\nend\n",
        "b.rb": "def helper\nend\n",
    })
    assert calls(edges) == [("a.rb::A.go", "b.rb::helper", 0.3, Resolution.NAME_GUESS)]


def test_name_guess_splits_confidence_and_gives_up_above_the_cutoff() -> None:
    def project(copies: int) -> dict[str, str]:
        files = {f"d{i}.rb": "def shared\nend\n" for i in range(copies)}
        files["main.rb"] = "def start\n  shared()\nend\n"
        return files

    two = calls(resolve(project(2)))
    assert [c[2] for c in two] == [0.3, 0.3]
    four = calls(resolve(project(4)))
    assert [round(c[2], 2) for c in four] == [0.25] * 4
    assert calls(resolve(project(MAX_GUESSES + 1))) == []


def test_name_guess_stays_inside_the_callers_language() -> None:
    edges = resolve({"a.rb": "def go\n  helper()\nend\n", "b.go": "package b\nfunc helper() {}\n"})
    assert calls(edges) == []


def test_go_unqualified_call_reaches_only_package_level_functions() -> None:
    edges = resolve({
        "p/a.go": "package p\nfunc run() { Add() }\n",
        "p/b.go": "package p\ntype T struct{}\nfunc (t *T) Add() {}\nfunc Add() {}\n",
    })
    assert calls(edges) == [("p/a.go::run", "p/b.go::Add", 1.0, Resolution.IMPORT_SCOPED)]


def test_go_other_package_functions_are_not_in_scope_without_an_import() -> None:
    edges = resolve({
        "p/a.go": "package p\nfunc run() { helper() }\n",
        "q/b.go": "package q\nfunc helper() {}\n",
    })
    (call,) = calls(edges)
    assert call[3] is Resolution.NAME_GUESS and call[2] == 0.3


def test_go_dot_import_brings_names_in_unqualified() -> None:
    edges = resolve({
        "main.go": 'package main\nimport . "example.com/shop/store"\nfunc run() { New() }\n',
        "store/s.go": "package store\nfunc New() {}\n",
    })
    assert ("main.go::run", "store/s.go::New", 1.0, Resolution.IMPORT_SCOPED) in calls(edges)


def test_go_import_edges_point_at_the_files_that_are_called_into() -> None:
    edges = resolve({
        "main.go": 'package main\nimport "example.com/shop/store"\nfunc run() { store.B() }\n',
        "store/a.go": "package store\nfunc A() {}\n",
        "store/b.go": "package store\nfunc B() {}\n",
    })
    imports = [e for e in edges if e.kind is EdgeKind.IMPORTS]
    assert [e.dst_id.split("/", 1)[1] for e in imports] == ["store/b.go::"]


def test_go_import_of_an_uncalled_package_points_at_each_file_with_split_confidence() -> None:
    edges = resolve({
        "main.go": 'package main\nimport _ "example.com/shop/store"\n',
        "store/a.go": "package store\nfunc A() {}\n",
        "store/b.go": "package store\nfunc B() {}\n",
    })
    imports = [e for e in edges if e.kind is EdgeKind.IMPORTS]
    assert sorted(e.confidence for e in imports) == [0.5, 0.5]
    assert {e.attrs["files_in_package"] for e in imports} == {2}


def test_external_import_makes_an_external_call_and_import() -> None:
    edges = resolve({"a.go": 'package a\nimport "fmt"\nfunc run() { fmt.Println() }\n'})
    assert calls(edges) == [("a.go::run", "::external:fmt.Println", 1.0, Resolution.IMPORT_SCOPED)]
    (imp,) = [e for e in edges if e.kind is EdgeKind.IMPORTS]
    assert imp.dst_id.endswith("::external:fmt") and imp.resolution is Resolution.STRUCTURAL


def test_java_overloads_are_candidates_that_share_the_confidence() -> None:
    edges = resolve({
        "A.java": "class A { void go() { log(1); } void log(int a) {} void log(String a) {} }"
    })
    assert sorted(c[2] for c in calls(edges)) == [0.5, 0.5]


def test_java_unqualified_call_prefers_the_enclosing_class_over_other_classes() -> None:
    edges = resolve({
        "A.java": "class A { void go() { run(); } void run() {} }\nclass B { void run() {} }\n"
    })
    assert calls(edges) == [("A.java::A.go", "A.java::A.run", 1.0, Resolution.IMPORT_SCOPED)]


def test_java_static_import_resolves_an_unqualified_call() -> None:
    edges = resolve({
        "p/Main.java": (
            "package p;\nimport static q.U.twice;\nclass Main { void go() { twice(); } }"
        ),
        "q/U.java": "package q;\nclass U { static void twice() {} static void thrice() {} }",
    })
    assert ("p/Main.java::Main.go", "q/U.java::U.twice", 1.0, Resolution.IMPORT_SCOPED) in calls(
        edges
    )


def test_java_import_of_a_missing_class_is_external() -> None:
    edges = resolve({"A.java": "import x.y.Z;\nclass A { void go() { Z.run(); } }"})
    assert calls(edges) == [("A.java::A.go", "::external:x.y.Z.run", 1.0, Resolution.IMPORT_SCOPED)]


@pytest.mark.parametrize("language_file", ["a.rb"])
def test_unresolvable_calls_stay_raw(language_file: str) -> None:
    assert resolve({language_file: "def go\n  nowhere()\nend\n"}) == []


def test_snapshot_id_in_edges_comes_from_the_parse() -> None:
    edges = resolve({"a.rb": "def a\n  b()\nend\ndef b\nend\n"})
    assert edges and edges[0].src_id.startswith(SNAPSHOT + "/")
