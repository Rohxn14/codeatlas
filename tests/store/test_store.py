import sqlite3
from pathlib import Path

import pytest

from codeatlas.indexer.adapter import SymbolIndex
from codeatlas.models import (
    Edge,
    EdgeKind,
    FileRecord,
    Node,
    NodeKind,
    RawCall,
    Resolution,
    Snapshot,
    Span,
    Tier,
    make_key,
    make_node_id,
    make_snapshot_id,
)
from codeatlas.store import GraphStore, StoreError

REPO = "demo"
SID = make_snapshot_id(REPO, "aaaaaaaaaaaaaaaa")
SID2 = make_snapshot_id(REPO, "bbbbbbbbbbbbbbbb")


def snap(sid: str = SID, sha: str = "aaaaaaaaaaaaaaaa", at: str = "2026-10-30T09:00:00Z"):
    return Snapshot(sid, REPO, sha, at, "0.1.0", "/tmp/demo", ("max_files",))


def node(path: str, qualname: str, kind: NodeKind, sid: str = SID, **extra) -> Node:
    key = make_key(path, qualname)
    name = qualname.rsplit(".", 1)[-1] if qualname else path.rsplit("/", 1)[-1]
    return Node(
        id=make_node_id(sid, key),
        key=key,
        snapshot_id=sid,
        kind=kind,
        language="python",
        name=name,
        qualname=qualname,
        path=path,
        span=Span(1, 9, 0, 4),
        **extra,
    )


MODULE = node("backend/users.py", "", NodeKind.MODULE)
CLASS = node("backend/users.py", "UserService", NodeKind.CLASS, attrs={"bases": ["Base"]})
SAVE = node(
    "backend/users.py",
    "UserService.save",
    NodeKind.FUNCTION,
    signature="def save(self, user: User) -> None",
    docstring="Persist a user to the database.",
    owner_key=CLASS.key,
    attrs={"decorators": ["traced"], "is_async": False},
)
SAVE_ALL = node("backend/users.py", "save_all", NodeKind.FUNCTION, docstring="Save many users.")
OTHER = node("backend/other.py", "", NodeKind.MODULE)
HELPER = node("backend/other.py", "helper", NodeKind.FUNCTION, docstring="Calls save often.")
FILES = [
    FileRecord("backend/users.py", "python", Tier.DEEP, "h1", 120),
    FileRecord("backend/other.py", "python", Tier.DEEP, "h2", 40),
]
EDGES = [
    Edge(MODULE.id, CLASS.id, EdgeKind.CONTAINS, 1.0, Resolution.STRUCTURAL),
    Edge(SAVE_ALL.id, SAVE.id, EdgeKind.CALLS, 0.9, Resolution.SELF_METHOD, 5, {"via": "x"}),
    Edge(HELPER.id, SAVE.id, EdgeKind.CALLS, 0.25, Resolution.NAME_GUESS, 3, {"candidates": 4}),
]


@pytest.fixture
def store() -> GraphStore:
    s = GraphStore(":memory:")
    s.create_snapshot(snap())
    s.write_files(SID, FILES)
    s.write_nodes([MODULE, CLASS, SAVE, SAVE_ALL, OTHER, HELPER])
    s.write_edges(SID, EDGES)
    return s


def test_snapshot_round_trip(store: GraphStore) -> None:
    assert store.get_snapshot(SID) == snap()
    assert store.get_snapshot("nope@1") is None


def test_latest_snapshot_picks_newest(store: GraphStore) -> None:
    newer = snap(SID2, "bbbbbbbbbbbbbbbb", "2026-10-31T09:00:00Z")
    store.create_snapshot(newer)
    assert store.latest_snapshot(REPO) == newer
    assert store.latest_snapshot("other") is None


def test_file_round_trip(store: GraphStore) -> None:
    assert store.files(SID) == sorted(FILES, key=lambda f: f.path)
    assert store.file_hashes(SID) == {"backend/users.py": "h1", "backend/other.py": "h2"}


def test_node_round_trip(store: GraphStore) -> None:
    for n in (MODULE, CLASS, SAVE, SAVE_ALL, OTHER, HELPER):
        assert store.node(n.id) == n
    assert store.node("missing") is None


def test_edge_round_trip(store: GraphStore) -> None:
    assert store.edges(SID) == EDGES


def test_raw_calls_round_trip_and_resolution(store: GraphStore) -> None:
    resolved = RawCall(SAVE_ALL.key, "self.save", "save", "self", 5)
    unresolved = RawCall(HELPER.key, "mystery()", "mystery", None, 8)
    store.write_raw_calls(SID, [resolved, unresolved])
    assert store.raw_calls(SID) == [(resolved, False), (unresolved, False)]
    assert store.mark_resolved_calls(SID) == 1
    assert store.raw_calls(SID, resolved=False) == [(unresolved, False)]
    assert store.raw_calls(SID, resolved=True) == [(resolved, True)]


def test_duplicate_node_ids_raise(store: GraphStore) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        store.write_nodes([SAVE_ALL, SAVE_ALL])


def test_lookups(store: GraphStore) -> None:
    assert store.nodes_by_key(SAVE.key, SID) == [SAVE]
    assert store.nodes_by_name(SID, "save") == [SAVE]
    assert store.nodes_by_name(SID, "save", language="go") == []
    assert store.nodes_in_file(SID, "backend/other.py") == [OTHER, HELPER]
    assert store.members(SID, CLASS.key) == [SAVE]
    assert store.module_for_path(SID, "backend/users.py") == MODULE


def test_edges_from_and_to(store: GraphStore) -> None:
    assert store.edges_to(SAVE.id) == EDGES[1:]
    assert store.edges_to(SAVE.id, min_confidence=0.5) == [EDGES[1]]
    assert store.edges_from(MODULE.id, kinds=[EdgeKind.CALLS]) == []
    assert store.edges_from(MODULE.id, kinds=[EdgeKind.CONTAINS]) == [EDGES[0]]
    assert store.edges_from("unknown@1/x.py::") == []


def test_edges_found_when_repo_name_has_a_slash() -> None:
    sid = make_snapshot_id("org/app", "cccccccccccccccc")
    s = GraphStore(":memory:")
    s.create_snapshot(Snapshot(sid, "org/app", "c" * 16, "2026-10-30T09:00:00Z", "0.1", "x"))
    a, b = node("a.py", "f", NodeKind.FUNCTION, sid), node("b.py", "g", NodeKind.FUNCTION, sid)
    s.write_nodes([a, b])
    s.write_edges(sid, [Edge(a.id, b.id, EdgeKind.CALLS, 1.0, Resolution.DIRECT, 2)])
    assert [e.dst_id for e in s.edges_from(a.id)] == [b.id]


def test_search_puts_exact_name_first(store: GraphStore) -> None:
    hits = store.search_text(SID, "save", k=5)
    assert hits[0][0] == SAVE
    found = {n.id for n, _ in hits}
    assert {SAVE_ALL.id, HELPER.id} <= found
    assert all(score > 0 for _, score in hits)


def test_search_ignores_fts_syntax_and_other_snapshots(store: GraphStore) -> None:
    assert store.search_text(SID, '"save" AND (*') != []
    assert store.search_text(SID, "  ") == []
    assert store.search_text(SID2, "save") == []


def test_copy_unchanged_rewrites_ids_and_keeps_keys(store: GraphStore) -> None:
    store.create_snapshot(snap(SID2, "bbbbbbbbbbbbbbbb", "2026-10-31T09:00:00Z"))
    assert store.copy_unchanged(SID, SID2, ["backend/other.py"]) == 2
    copied = store.nodes_in_file(SID2, "backend/other.py")
    assert [n.key for n in copied] == [OTHER.key, HELPER.key]
    assert [n.id for n in copied] == [make_node_id(SID2, OTHER.key), make_node_id(SID2, HELPER.key)]
    assert all(n.snapshot_id == SID2 for n in copied)
    assert copied[1].docstring == HELPER.docstring
    assert store.nodes_in_file(SID2, "backend/users.py") == []
    assert store.edges(SID2) == []
    # The copies are searchable too, and the old snapshot is untouched.
    assert store.search_text(SID2, "helper")[0][0].id == copied[1].id
    assert store.node(HELPER.id) == HELPER


def test_symbol_index(store: GraphStore) -> None:
    index = store.symbol_index(SID)
    assert isinstance(index, SymbolIndex)
    assert index.by_key(SAVE.key) == SAVE
    assert index.by_key("nope::") is None
    assert index.by_name("helper", "python") == [HELPER]
    assert index.module_for_path("backend/other.py") == OTHER
    assert index.members(CLASS.key) == [SAVE]
    assert [f.path for f in index.files()] == ["backend/other.py", "backend/users.py"]


def test_graph_view(store: GraphStore) -> None:
    g = store.graph(SID)
    assert g.number_of_nodes() == 6
    assert g.number_of_edges() == 3
    data = g.get_edge_data(SAVE_ALL.id, SAVE.id)[0]
    assert data == {
        "kind": EdgeKind.CALLS,
        "confidence": 0.9,
        "resolution": Resolution.SELF_METHOD,
        "line": 5,
    }
    calls_only = store.graph(SID, kinds=[EdgeKind.CALLS], min_confidence=0.5)
    assert list(calls_only.edges()) == [(SAVE_ALL.id, SAVE.id)]


def test_export_json_matches_contract_shape(store: GraphStore) -> None:
    out = store.export_json(SID)
    assert set(out) == {"snapshot", "nodes", "edges"}
    assert out["snapshot"] == {
        "id": SID,
        "repo": REPO,
        "commit_sha": "aaaaaaaaaaaaaaaa",
        "indexed_at": "2026-10-30T09:00:00Z",
        "indexer_version": "0.1.0",
        "source": "/tmp/demo",
        "limits_hit": ["max_files"],
    }
    assert out["nodes"][2] == {
        "key": SAVE.key,
        "kind": "function",
        "language": "python",
        "path": "backend/users.py",
        "span": {"start_line": 1, "end_line": 9},
    }
    assert out["edges"][1] == {
        "src_key": SAVE_ALL.key,
        "dst_key": SAVE.key,
        "kind": "calls",
        "confidence": 0.9,
        "resolution": "self_method",
        "line": 5,
    }
    with pytest.raises(KeyError):
        store.export_json("nope@1")


def test_file_database_reopens(tmp_path: Path) -> None:
    db = tmp_path / "atlas.db"
    with GraphStore(db) as s:
        s.create_snapshot(snap())
        s.write_nodes([SAVE])
    with GraphStore(db) as s:
        assert s.node(SAVE.id) == SAVE
        assert s.search_text(SID, "save")[0][0] == SAVE


def test_schema_version_mismatch_asks_for_reindex(tmp_path: Path) -> None:
    db = tmp_path / "atlas.db"
    GraphStore(db).close()
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")
    conn.close()
    with pytest.raises(StoreError, match="re-index"):
        GraphStore(db)


def test_missing_fts5_names_sqlite_version(monkeypatch: pytest.MonkeyPatch) -> None:
    class NoFts:
        def execute(self, sql: str) -> None:
            raise sqlite3.OperationalError("no such module: fts5")

        def close(self) -> None:
            pass

    monkeypatch.setattr("codeatlas.store.schema.sqlite3.connect", lambda _: NoFts())
    with pytest.raises(StoreError, match=sqlite3.sqlite_version):
        GraphStore(":memory:")


def test_only_the_call_that_resolved_is_marked(store: GraphStore) -> None:
    # foo(mystery()) on one line: only `save` resolved, so `mystery` stays unresolved.
    outer = RawCall(HELPER.key, "save", "save", None, 3)
    inner = RawCall(HELPER.key, "mystery", "mystery", None, 3)
    store.write_raw_calls(SID, [outer, inner])
    assert store.mark_resolved_calls(SID) == 1
    assert store.raw_calls(SID, resolved=False) == [(inner, False)]


def test_constructor_call_is_marked_by_its_init_on_the_same_line() -> None:
    s = GraphStore(":memory:")
    s.create_snapshot(snap())
    init = node("backend/users.py", "UserService.__init__", NodeKind.FUNCTION)
    s.write_nodes([MODULE, CLASS, init, HELPER])
    s.write_edges(SID, [Edge(HELPER.id, init.id, EdgeKind.CALLS, 1.0, Resolution.DIRECT, 4)])
    s.write_raw_calls(SID, [RawCall(HELPER.key, "UserService", "UserService", None, 4)])
    assert s.mark_resolved_calls(SID) == 1


def test_writes_for_an_unknown_snapshot_raise() -> None:
    s = GraphStore(":memory:")
    with pytest.raises(KeyError, match="create_snapshot"):
        s.write_nodes([MODULE])
    with pytest.raises(KeyError):
        s.write_files(SID, FILES)
    with pytest.raises(KeyError):
        s.write_edges(SID, EDGES)
    with pytest.raises(KeyError):
        s.write_raw_calls(SID, [RawCall(HELPER.key, "x", "x", None, 1)])


def test_delete_snapshot_allows_indexing_the_same_commit_again(store: GraphStore) -> None:
    store.write_raw_calls(SID, [RawCall(HELPER.key, "x", "x", None, 1)])
    assert store.delete_snapshot(SID) == 6
    assert store.get_snapshot(SID) is None
    assert store.search_text(SID, "save") == []
    assert store.edges(SID) == [] and store.files(SID) == [] and store.raw_calls(SID) == []
    store.create_snapshot(snap())  # no IntegrityError the second time
    store.write_nodes([MODULE, SAVE_ALL])
    assert [n.name for n, _ in store.search_text(SID, "save_all")] == ["save_all"]


def test_failed_schema_check_closes_the_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from codeatlas.store import sqlite as store_module

    def broken(conn: object) -> None:
        raise RuntimeError("schema mismatch")

    monkeypatch.setattr(store_module, "init_schema", broken)
    db = tmp_path / "x.db"
    with pytest.raises(RuntimeError):
        GraphStore(db)
    db.unlink()  # would fail on Windows if the connection were still open
