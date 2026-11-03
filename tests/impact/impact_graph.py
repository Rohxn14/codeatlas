"""A small hand-built snapshot with known edges, so every score in the tests is exact."""

from __future__ import annotations

from codeatlas.models import (
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    Resolution,
    Snapshot,
    Span,
    make_node_id,
    make_snapshot_id,
)
from codeatlas.store import GraphStore

SHA = "a1b2c3d4e5f6" + "0" * 28
SNAP = make_snapshot_id("demo", SHA)


def _node(key: str, kind: NodeKind, start: int, end: int, language: str = "python",
          **kw: object) -> Node:
    path, qualname = key.split("::", 1)
    return Node(make_node_id(SNAP, key), key, SNAP, kind, language, qualname.rsplit(".", 1)[-1],
                qualname, path, Span(start, end), **kw)  # type: ignore[arg-type]


def _edge(src: str, dst: str, kind: EdgeKind, conf: float, res: Resolution,
          **attrs: object) -> Edge:
    return Edge(make_node_id(SNAP, src), make_node_id(SNAP, dst), kind, conf, res, None, attrs)


NODES = [
    _node("app/repo.py::", NodeKind.MODULE, 1, 12),
    _node("app/repo.py::Repo", NodeKind.CLASS, 2, 12),
    _node("app/repo.py::Repo.save", NodeKind.FUNCTION, 3, 6, owner_key="app/repo.py::Repo"),
    _node("app/repo.py::Repo.load", NodeKind.FUNCTION, 8, 12, owner_key="app/repo.py::Repo"),
    _node("app/service.py::", NodeKind.MODULE, 1, 9),
    _node("app/service.py::create", NodeKind.FUNCTION, 3, 5),
    _node("app/service.py::rename", NodeKind.FUNCTION, 7, 9),
    _node("app/api.py::", NodeKind.MODULE, 1, 5),
    _node("app/api.py::handler", NodeKind.FUNCTION, 3, 5),
    _node("app/util.py::", NodeKind.MODULE, 1, 3),
    _node("app/other.py::", NodeKind.MODULE, 1, 2),
    _node("app/settings.py::", NodeKind.MODULE, 1, 2),
    _node("tests/test_service.py::", NodeKind.MODULE, 1, 5),
    _node("tests/test_service.py::test_create", NodeKind.TEST, 3, 5),
    _node("tests/test_repo.py::", NodeKind.MODULE, 1, 5),
    _node("tests/test_repo.py::test_save", NodeKind.TEST, 3, 5),
    _node("tests/test_util.py::", NodeKind.MODULE, 1, 3),
    _node("README.md::", NodeKind.MODULE, 1, 20, language="markdown"),
]

EDGES = [
    _edge("app/service.py::create", "app/repo.py::Repo.save", EdgeKind.CALLS, 0.9,
          Resolution.SELF_METHOD),
    _edge("app/api.py::handler", "app/service.py::create", EdgeKind.CALLS, 1.0,
          Resolution.DIRECT),
    _edge("app/service.py::rename", "app/service.py::create", EdgeKind.CALLS, 0.5,
          Resolution.IMPORT_SCOPED),
    _edge("tests/test_service.py::test_create", "app/service.py::create", EdgeKind.CALLS, 1.0,
          Resolution.DIRECT),
    _edge("app/service.py::", "app/repo.py::Repo", EdgeKind.IMPORTS, 1.0,
          Resolution.STRUCTURAL),
    _edge("app/api.py::", "app/service.py::create", EdgeKind.IMPORTS, 1.0,
          Resolution.STRUCTURAL),
    _edge("tests/test_service.py::", "app/service.py::create", EdgeKind.IMPORTS, 1.0,
          Resolution.STRUCTURAL),
    _edge("app/other.py::", "app/repo.py::", EdgeKind.IMPORTS, 1.0, Resolution.STRUCTURAL),
    _edge("tests/test_repo.py::test_save", "app/repo.py::Repo.save", EdgeKind.TESTS, 1.0,
          Resolution.DIRECT),
    _edge("tests/test_util.py::", "app/util.py::", EdgeKind.TESTS, 0.8, Resolution.CONVENTION),
    _edge("app/repo.py::", "app/settings.py::", EdgeKind.CO_CHANGES, 0.6, Resolution.HISTORY,
          support=3, source_commits=5),
    _edge("app/repo.py::", "app/api.py::", EdgeKind.CO_CHANGES, 0.5, Resolution.HISTORY,
          support=5, source_commits=10),
]


def build_store() -> GraphStore:
    store = GraphStore(":memory:")
    store.create_snapshot(Snapshot(SNAP, "demo", SHA, "2026-11-03T00:00:00Z", "0.1.0", "."))
    store.write_nodes(NODES)
    store.write_edges(SNAP, EDGES)
    return store


def key(path_and_name: str) -> str:
    return path_and_name
