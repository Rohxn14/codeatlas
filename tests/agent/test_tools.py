"""Every tool on the small hand-built repository, with exact expected results."""

import json
import sys

import pytest

from codeatlas.agent.tools import MAX_RESULT_CHARS, TOOL_NAMES, ToolSet
from codeatlas.models import (
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    Resolution,
    Span,
    make_node_id,
)

from .support import SNAP


@pytest.fixture
def tools(store):
    return ToolSet(store, SNAP)


def keys(items):
    return [i["key"] for i in items]


def test_twelve_tools_and_no_run_tests(tools):
    assert len(TOOL_NAMES) == 12 and "run_tests" not in TOOL_NAMES
    assert [s.name for s in tools.specs] == list(TOOL_NAMES)
    assert all(s.parameters["type"] == "object" for s in tools.specs)


def test_search_symbols_exact_first(tools):
    out = tools.call("search_symbols", {"name": "save"})
    assert keys(out["symbols"]) == ["app/repo.py::Repo.save"]
    assert out["symbols"][0]["citation"] == f"{SNAP}:app/repo.py:2"
    out = tools.call("search_symbols", {"name": "re"})  # prefix matches first, then substring
    assert keys(out["symbols"]) == ["app/repo.py::Repo", "app/service.py::rename",
                                    "app/service.py::create", "tests/test_service.py::test_create"]
    assert {s["match"] for s in out["symbols"]} == {"partial"}


def test_search_symbols_kind_and_errors(tools):
    out = tools.call("search_symbols", {"name": "test", "kind": "test"})
    assert keys(out["symbols"]) == ["tests/test_service.py::test_create"]
    assert "error" in tools.call("search_symbols", {"name": "x", "kind": "nope"})
    assert "error" in tools.call("search_symbols", {"name": " "})


def test_search_symbols_reads_a_dotted_name_as_module_and_symbol(tools):
    # How a model writes it (`contracts.validate`); on Nov 19 this found nothing.
    out = tools.call("search_symbols", {"name": "service.create"})
    assert keys(out["symbols"]) == ["app/service.py::create"]
    assert out["symbols"][0]["match"] == "exact"
    out = tools.call("search_symbols", {"name": "app.repo.Repo.save"})
    assert keys(out["symbols"]) == ["app/repo.py::Repo.save"]
    out = tools.call("search_symbols", {"name": "repo.Repo"})
    assert keys(out["symbols"]) == ["app/repo.py::Repo"]
    # Whole parts only: "ice" is the end of "service", not a part of the path.
    assert tools.call("search_symbols", {"name": "ice.create"})["total"] == 0


def test_search_symbols_limit_reports_truncation(tools):
    out = tools.call("search_symbols", {"name": "e", "limit": 1})
    assert len(out["symbols"]) == 1 and out["truncated"] is True and out["total"] > 1


def test_get_symbol_source(tools):
    out = tools.call("get_symbol_source", {"key": "app/repo.py::Repo.save"})
    assert out["signature"] == "def save(self, user)"
    assert out["docstring"] == "Store a user."
    assert (out["line"], out["end_line"]) == (2, 4)
    assert out["source"].splitlines()[0] == "2:     def save(self, user):"
    assert out["truncated"] is False
    assert out["citation"] == f"{SNAP}:app/repo.py:2"


def test_get_symbol_source_accepts_unique_qualname_and_reports_ambiguity(tools):
    assert tools.call("get_symbol_source", {"key": "Repo.save"})["key"] == "app/repo.py::Repo.save"
    assert "error" in tools.call("get_symbol_source", {"key": "nothing.here"})


def test_get_symbol_source_without_checkout(store):
    store._conn.execute("UPDATE snapshots SET source = 'C:/gone/nowhere'")
    out = ToolSet(store, SNAP).call("get_symbol_source", {"key": "app/service.py::create"})
    assert out["source"] is None and "not on disk" in out["note"]


def test_get_symbol_source_url_reads_from_repos_dir(store, tmp_path):
    from codeatlas.config import Config

    clone = tmp_path / "data" / "repos" / "o__r"
    (clone / "app").mkdir(parents=True)
    (clone / "app" / "repo.py").write_text("class Repo:\n    def save(self, user):\n"
                                           "        pass\n        return 1\n")
    store._conn.execute("UPDATE snapshots SET source = 'https://github.com/o/r'")
    ts = ToolSet(store, SNAP, Config(data_dir=str(tmp_path / "data")))
    out = ts.call("get_symbol_source", {"key": "app/repo.py::Repo.save"})
    assert "pass" in out["source"]


def test_get_symbol_source_truncates_long_bodies(store, source_dir):
    (source_dir / "app" / "repo.py").write_text("\n".join(f"x = {'1' * 90}" for _ in range(100)))
    store._conn.execute("UPDATE nodes SET end_line = 100 WHERE key = 'app/repo.py::Repo.save'")
    out = ToolSet(store, SNAP).call("get_symbol_source", {"key": "app/repo.py::Repo.save"})
    assert out["truncated"] is True
    assert len(json.dumps(out)) <= MAX_RESULT_CHARS


def test_get_file_symbols(tools):
    out = tools.call("get_file_symbols", {"path": "app/repo.py"})
    assert keys(out["symbols"]) == ["app/repo.py::Repo", "app/repo.py::Repo.save"]
    assert out["lines"] == 4 and out["citation"] == f"{SNAP}:app/repo.py:1"
    assert "error" in tools.call("get_file_symbols", {"path": "missing.py"})


def test_find_callers_depth_and_confidence(tools):
    key = "app/repo.py::Repo.save"
    one = tools.call("find_callers", {"key": key})
    assert [(r["key"], r["confidence"]) for r in one["results"]] == [("app/service.py::create",
                                                                      0.5)]
    two = tools.call("find_callers", {"key": key, "depth": 2})
    assert [(r["key"], r["confidence"]) for r in two["results"]] == [
        ("app/service.py::create", 0.5), ("app/service.py::rename", 0.5)]
    none = tools.call("find_callers", {"key": key, "depth": 2, "min_confidence": 0.9})
    assert none["results"] == [] and none["truncated"] is False


def test_find_callees(tools):
    out = tools.call("find_callees", {"key": "app/service.py::rename", "depth": 2})
    assert [(r["key"], r["confidence"]) for r in out["results"]] == [
        ("app/service.py::create", 1.0), ("app/repo.py::Repo.save", 0.5)]
    assert out["results"][0]["citation"] == f"{SNAP}:app/service.py:3"


def test_get_imports_both_directions(tools):
    out = tools.call("get_imports", {"path": "app/service.py"})
    assert keys(out["imports"]) == ["app/repo.py::"]
    assert keys(out["imported_by"]) == ["tests/test_service.py::"]
    assert out["imports"][0]["resolution"] == "structural"
    assert "error" in tools.call("get_imports", {"path": "nope.py"})


def test_compare_symbol_across_snapshots(store, tools):
    other = "demo@aaaaaaaaaaaa"
    store.create_snapshot(type(store.get_snapshot(SNAP))(other, "demo", "a" * 40,
                                                       "2026-11-02T00:00:00Z", "0.1.0", "x"))
    store.write_nodes([Node(make_node_id(other, "app/service.py::create"),
                            "app/service.py::create", other, NodeKind.FUNCTION, "python",
                            "create", "create", "app/service.py", Span(3, 9),
                            signature="def create(user, now)")])
    out = tools.call("compare_symbol_across_snapshots",
                     {"key": "app/service.py::create", "snapshot_a": SNAP, "snapshot_b": other})
    assert out["a"]["signature"] == "def create(user)" and out["a"]["span"] == [3, 4]
    assert out["b"]["signature"] == "def create(user, now)" and out["b"]["span"] == [3, 9]
    assert out["signature_changed"] is True
    gone = tools.call("compare_symbol_across_snapshots",
                      {"key": "app/repo.py::Repo.save", "snapshot_a": SNAP, "snapshot_b": other})
    assert gone["b"] == {"snapshot": other, "exists": False} and gone["signature_changed"]
    assert "error" in tools.call("compare_symbol_across_snapshots",
                                 {"key": "x", "snapshot_a": SNAP, "snapshot_b": "nope"})


def test_traverse(tools):
    out = tools.call("traverse", {"key": "app/service.py::rename", "edge_kinds": ["calls"],
                                  "depth": 3})
    assert [(r["key"], r["depth"]) for r in out["results"]] == [
        ("app/service.py::create", 1), ("app/repo.py::Repo.save", 2)]
    back = tools.call("traverse", {"key": "app/service.py::create", "edge_kinds": ["calls",
                                   "tests"], "direction": "in"})
    assert sorted(keys(back["results"])) == ["app/service.py::rename",
                                             "tests/test_service.py::test_create"]
    assert "error" in tools.call("traverse", {"key": "app/service.py::create",
                                              "edge_kinds": ["bogus"]})
    assert "error" in tools.call("traverse", {"key": "app/service.py::create",
                                              "edge_kinds": ["calls"], "direction": "up"})


def test_traverse_depth_is_capped_at_three(tools):
    out = tools.call("traverse", {"key": "app/service.py::rename", "edge_kinds": ["calls"],
                                  "depth": 99})
    assert out["depth"] == 3


def test_impact(tools):
    out = tools.call("impact", {"keys": ["app/repo.py::Repo.save"]})
    # Engine scores: confidence times 0.8 per hop; `affected` uses non-history evidence.
    assert [(r["key"], r["confidence"]) for r in out["affected"]] == [
        ("app/repo.py::Repo", 0.8), ("app/service.py::", 0.4), ("app/service.py::create", 0.4),
        ("app/service.py::rename", 0.32), ("tests/test_service.py::test_create", 0.288)]
    assert {e["signal"] for e in out["affected"][2]["evidence"]} == {"graph"}
    assert keys(out["co_changed_files"]) == ["app/service.py::"]
    assert out["co_changed_files"][0]["changed_with"] == "app/repo.py"


def test_impact_unknown_key(tools):
    out = tools.call("impact", {"keys": ["nope"]})
    assert "error" in out and out["problems"][0]["key"] == "nope"


def test_select_tests(tools):
    out = tools.call("select_tests", {"keys": ["app/repo.py::Repo.save"]})
    assert [(t["key"], t["confidence"], t["covers"]) for t in out["tests"]] == [
        ("tests/test_service.py::test_create", 0.288, "app/service.py::create")]


def test_unknown_tool_and_bad_arguments(tools):
    assert "error" in tools.call("run_tests", {})
    assert "bad arguments" in tools.call("find_callers", {"nope": 1})["error"]
    assert "bad arguments" in tools.call("find_callers", {})["error"]


def test_big_result_is_truncated_under_budget(store):
    nodes, edges = [], []
    target = make_node_id(SNAP, "app/repo.py::Repo.save")
    for i in range(200):
        key = f"app/gen.py::caller_with_a_rather_long_name_{i}"
        nodes.append(Node(make_node_id(SNAP, key), key, SNAP, NodeKind.FUNCTION, "python",
                          f"caller_with_a_rather_long_name_{i}",
                          f"caller_with_a_rather_long_name_{i}", "app/gen.py", Span(i + 1, i + 1),
                          signature="def f(a, b, c)"))
        edges.append(Edge(nodes[-1].id, target, EdgeKind.CALLS, 0.9, Resolution.DIRECT, 1))
    store.write_nodes(nodes)
    store.write_edges(SNAP, edges)
    ts = ToolSet(store, SNAP)
    out = ts.call("find_callers", {"key": "app/repo.py::Repo.save"})
    assert out["truncated"] is True and out["omitted"] > 0 and out["total"] == 201
    assert len(ts.call_json("find_callers", {"key": "app/repo.py::Repo.save"})) <= MAX_RESULT_CHARS
    assert all(r["citation"].startswith(SNAP + ":app/") for r in out["results"])


def test_semantic_search_falls_back_to_text(tools, monkeypatch):
    monkeypatch.setitem(sys.modules, "codeatlas.search", None)  # `import` now raises ImportError
    out = tools.call("semantic_search", {"query": "save user"})
    assert out["engine"] == "text" and "not available" in out["note"]
    assert out["hits"][0]["key"] == "app/repo.py::Repo.save"
    assert out["hits"][0]["found_by"] == ["bm25"]


def test_semantic_search_survives_a_failing_hybrid_engine(tools, monkeypatch):
    class Boom:
        def __init__(self, *a):
            raise RuntimeError("model missing")

    import codeatlas.search as search

    monkeypatch.setattr(search, "HybridSearch", Boom, raising=False)
    out = tools.call("semantic_search", {"query": "save"})
    assert out["engine"] == "text" and "model missing" in out["note"]


def test_semantic_search_uses_hybrid_when_present(tools, store, monkeypatch):
    class Hit:
        def __init__(self, node):
            self.node, self.score, self.sources = node, 0.5, ["bm25", "vector"]

    class Fake:
        def __init__(self, st, sid, embedder):
            self.st, self.sid = st, sid

        def search(self, query, k=10, docs=False):
            return [Hit(self.st.nodes_by_key("app/service.py::create", self.sid)[0])]

    import codeatlas.llm as llm
    import codeatlas.search as search

    monkeypatch.setattr(search, "HybridSearch", Fake, raising=False)
    class FakeEmbeddings:
        @classmethod
        def from_config(cls):
            return cls()

    monkeypatch.setattr(llm, "EmbeddingClient", FakeEmbeddings)
    out = tools.call("semantic_search", {"query": "make user"})
    assert out["engine"] == "hybrid" and out["hits"][0]["found_by"] == ["bm25", "vector"]


def test_get_imports_counts_importers_of_symbols_in_the_file(tmp_path):
    from codeatlas.indexer.pipeline import build_graph
    from codeatlas.store import GraphStore

    (tmp_path / "repo.py").write_text("class Repo:\n    def save(self):\n        pass\n")
    (tmp_path / "user_repo.py").write_text(
        "from repo import Repo\n\nclass UserRepo(Repo):\n    pass\n")
    st = GraphStore(":memory:")
    built = build_graph(str(tmp_path), st)
    out = ToolSet(st, built.snapshot_id).call("get_imports", {"path": "repo.py"})
    assert [row["path"] for row in out["imported_by"]] == ["user_repo.py"]


def test_search_docs_finds_only_sections_and_carries_their_text(tmp_path):
    from codeatlas.agent.tools import SECTION_TEXT_CHARS
    from codeatlas.indexer.pipeline.build import build_graph
    from codeatlas.store import GraphStore

    (tmp_path / "app.py").write_text("def install():\n    pass\n", encoding="utf-8")
    long_text = "Run the zeppelin installer. " + "more " * 400
    (tmp_path / "README.md").write_text(f"# Demo\n\n## Install\n{long_text}\n", encoding="utf-8")
    with GraphStore(":memory:") as store:
        built = build_graph(str(tmp_path), store)
        tools = ToolSet(store, built.snapshot_id)
        docs = tools.call("search_docs", {"query": "install"})
        (hit,) = docs["hits"]
        assert (hit["kind"], hit["name"], hit["path"], hit["line"]) == (
            "section", "Install", "README.md", 3)
        assert hit["text"].startswith("Run the zeppelin installer.")
        assert len(hit["text"]) == SECTION_TEXT_CHARS + len(" ...")
        assert hit["citation"].endswith(":README.md:3")
        code = tools.call("semantic_search", {"query": "install"})
        kinds = [h["kind"] for h in code["hits"]]
        assert "function" in kinds and "section" not in kinds
