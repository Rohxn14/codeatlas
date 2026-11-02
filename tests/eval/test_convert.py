"""Key mapping from SCIP ranges, on a two-file sample taken from the fixture's real index."""

import json
from pathlib import Path

from eval.oracle.convert import (
    collect_definitions,
    collect_references,
    innermost,
    oracle_graph,
    path_prefix,
)
from eval.oracle.graph import GraphNode
from eval.oracle.scip import Document, Index, Occurrence, index_from_dict

DATA = Path(__file__).parent / "data"
REPO = "backend/repo.py::"
USER_REPO = "backend/user_repo.py::"


def sample() -> Index:
    return index_from_dict(json.loads((DATA / "two_files.scip.json").read_text("utf-8")))


def test_definitions_get_keys_from_path_and_descriptors_and_spans_from_ranges():
    definitions = collect_definitions([(sample(), "")])
    by_key = {d.key: d for d in definitions.values()}
    assert set(by_key) == {
        REPO + "Repo", REPO + "Repo.__init__", REPO + "Repo.get", REPO + "Repo.all",
        REPO + "Repo.save", USER_REPO + "UserRepo", USER_REPO + "UserRepo.save",
        USER_REPO + "UserRepo.find_by_name",
    }
    save = by_key[USER_REPO + "UserRepo.save"]
    assert (save.kind, save.start_line, save.end_line) == ("function", 6, 9)
    assert by_key[REPO + "Repo"].kind == "class"


def test_references_inside_bodies_become_caller_callee_pairs():
    index = sample()
    references = collect_references([(index, "")], collect_definitions([(index, "")]))
    assert [(r.src_key, r.dst_key, r.line) for r in references] == [
        (USER_REPO + "UserRepo.find_by_name", REPO + "Repo.all", 12),
        (USER_REPO + "UserRepo.save", REPO + "Repo.save", 9),
    ]


def test_prefix_makes_project_paths_repo_relative():
    index = Index("file:///work/app/frontend", "scip-typescript", ())
    assert path_prefix(index, "file:///work/app") == "frontend/"
    assert path_prefix(Index("file:///work/app", "", ()), "file:///work/app") == ""
    assert path_prefix(Index("file:///elsewhere", "", ()), "file:///work/app") is None


def ts_index() -> Index:
    """A test file whose `it` callback calls `fetchUsers`; SCIP has no symbol for the test."""
    fetch = "scip-typescript npm web 1.0 src/`api.ts`/fetchUsers()."
    helper = "scip-typescript npm web 1.0 tests/`api.test.ts`/stub()."
    definition = Occurrence((0, 16, 0, 26), fetch, 1, (0, 0, 2, 1))
    api = Document("src/api.ts", "TypeScript", (definition,))
    test = Document("tests/api.test.ts", "TypeScript", (
        Occurrence((0, 9, 0, 19), fetch, 0),  # import: module level, dropped
        Occurrence((2, 9, 2, 13), helper, 1, (2, 0, 4, 1)),
        Occurrence((7, 4, 7, 8), helper, 0),
        Occurrence((8, 10, 8, 20), fetch, 0),
    ))
    return Index("file:///work/app/frontend", "scip-typescript", (api, test))


def test_node_list_adds_test_scopes_and_the_prefix_is_applied():
    index = ts_index()
    prefix = path_prefix(index, "file:///work/app")
    test_node = GraphNode(
        "frontend/tests/api.test.ts::api > lists", "test", "typescript",
        "frontend/tests/api.test.ts", 6, 10,
    )
    graph = oracle_graph({"id": "x"}, [(index, prefix)], [test_node])
    edges = {(e["src_key"], e["dst_key"], e["line"]) for e in graph["edges"]}
    assert edges == {
        (test_node.key, "frontend/tests/api.test.ts::stub", 8),
        (test_node.key, "frontend/src/api.ts::fetchUsers", 9),
    }
    keys = {n["key"] for n in graph["nodes"]}
    assert test_node.key in keys and "frontend/src/api.ts::" in keys
    assert all(e["resolution"] == "scip" and e["kind"] == "calls" for e in graph["edges"])


def test_without_a_node_list_test_callbacks_are_module_level():
    index = ts_index()
    assert oracle_graph({}, [(index, "")])["edges"] == []


def test_innermost_prefers_smaller_spans_then_node_list_scopes():
    scopes = [(1, 20, 1, "outer"), (5, 8, 1, "inner"), (5, 8, 0, "node")]
    assert innermost(scopes, 6) == "node"
    assert innermost(scopes, 12) == "outer"
    assert innermost(scopes, 30) is None



def test_module_level_references_are_counted_not_lost():
    from collections import Counter
    from dataclasses import replace

    from eval.oracle.scip import Document, Occurrence

    index = sample()
    definitions = collect_definitions([(index, "")])
    save = next(sym for sym, d in definitions.items() if d.key == REPO + "Repo.save")
    # A file that calls Repo.save at module level, outside any function.
    script = Document("main.py", "python", (Occurrence((20, 0, 20, 4), save, 0),))
    index = replace(index, documents=(*index.documents, script))
    skipped: Counter[str] = Counter()
    refs = collect_references([(index, "")], collect_definitions([(index, "")]), (), skipped)
    assert len(refs) == 2  # the two in function bodies, as before
    assert skipped["module_level_references"] >= 1
