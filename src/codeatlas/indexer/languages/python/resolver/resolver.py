"""`PythonResolver`: the deep-tier resolver for Python (IMPORTS, CALLS, INHERITS, TESTS)."""

from __future__ import annotations

import posixpath
from collections.abc import Sequence

from codeatlas.indexer.adapter import SymbolIndex
from codeatlas.indexer.languages.python.resolver.calls import (
    CallResolver,
    Target,
)
from codeatlas.indexer.languages.python.resolver.edges import import_edges, inherit_edges
from codeatlas.indexer.languages.python.resolver.names import Names
from codeatlas.indexer.languages.python.resolver.project import Project
from codeatlas.indexer.languages.python.resolver.tables import (
    ModuleTable,
    build_tables,
)
from codeatlas.indexer.languages.python.resolver.types import Typer
from codeatlas.models import Edge, EdgeKind, Node, NodeKind, ParseResult, make_node_id


class PythonResolver:
    """Turns the Python adapter's raw imports and calls into edges (see docs/explainers)."""

    languages = frozenset({"python"})

    def resolve(self, results: Sequence[ParseResult], index: SymbolIndex) -> list[Edge]:
        parsed = [r for r in results if r.language == "python" and r.nodes]
        if not parsed:
            return []
        snapshot = parsed[0].nodes[0].snapshot_id
        roots = _package_roots(parsed, index)
        project = Project((r.path for r in parsed), roots.values())
        tables = build_tables(parsed, project, _roots_by_path(parsed, roots))
        names = Names(tables, project)
        edges: list[Edge] = []
        for table in tables.values():
            edges += import_edges(table, names, project, snapshot)
        classes = [n for t in tables.values() for n in t.by_qualname.values()
                   if n.kind is NodeKind.CLASS]
        edges += inherit_edges(classes, names, snapshot)
        calls = call_edges(parsed, tables, CallResolver(names, Typer(names), tables), snapshot)
        return [*edges, *calls, *tests_edges(calls, tables, snapshot)]


def call_edges(
    parsed: Sequence[ParseResult],
    tables: dict[str, ModuleTable],
    resolver: CallResolver,
    snapshot: str,
) -> list[Edge]:
    """One CALLS edge per (caller, callee), at the first line, with its best confidence."""
    by_key = {n.key: n for t in tables.values() for n in t.by_qualname.values()}
    best: dict[tuple[str, str], Edge] = {}
    for result in parsed:
        for call in result.calls:
            caller = by_key.get(call.caller_key)
            if caller is None or caller.kind not in (NodeKind.FUNCTION, NodeKind.TEST):
                continue  # module-level calls have no CALLS edge in the contract
            for target in resolver.resolve(call, caller):
                _keep(best, _call_edge(caller, target, call.line, snapshot))
    return list(best.values())


def _call_edge(caller: Node, target: Target, line: int, snapshot: str) -> Edge:
    attrs = {"candidates": target.candidates} if target.candidates > 1 else {}
    return Edge(
        caller.id, make_node_id(snapshot, target.key), EdgeKind.CALLS,
        target.confidence, target.resolution, line, attrs,
    )


def _keep(best: dict[tuple[str, str], Edge], edge: Edge) -> None:
    pair = (edge.src_id, edge.dst_id)
    old = best.get(pair)
    if old is None:
        best[pair] = edge
        return
    line = min(n for n in (old.line, edge.line) if n is not None)
    winner = edge if edge.confidence > old.confidence else old
    best[pair] = Edge(winner.src_id, winner.dst_id, winner.kind, winner.confidence,
                      winner.resolution, line, winner.attrs)


def tests_edges(calls: list[Edge], tables: dict[str, ModuleTable], snapshot: str) -> list[Edge]:
    """A TESTS edge for each repository function a test calls, outside the test files."""
    node_by_id = {n.id: n for t in tables.values() for n in t.by_qualname.values()}
    test_paths = {n.path for n in node_by_id.values() if n.kind is NodeKind.TEST}
    found: list[Edge] = []
    for edge in calls:
        source, target = node_by_id.get(edge.src_id), node_by_id.get(edge.dst_id)
        if source is None or target is None or source.kind is not NodeKind.TEST:
            continue
        if target.kind is not NodeKind.FUNCTION or _is_test_file(target.path, test_paths):
            continue
        found.append(Edge(edge.src_id, edge.dst_id, EdgeKind.TESTS, edge.confidence,
                          edge.resolution, edge.line, dict(edge.attrs)))
    return found


def _is_test_file(path: str, test_paths: set[str]) -> bool:
    name = posixpath.basename(path)
    return (path in test_paths or name.startswith("test_") or name.endswith("_test.py")
            or name == "conftest.py")


def _package_roots(parsed: Sequence[ParseResult], index: SymbolIndex) -> dict[str, str]:
    """Package key -> its folder, for every package that contains one of these files."""
    roots: dict[str, str] = {}
    for result in parsed:
        key = result.nodes[0].attrs.get("package_key")
        if isinstance(key, str) and key not in roots:
            package = index.by_key(key)
            if package is not None:
                roots[key] = str(package.attrs.get("root", ""))
    return roots


def _roots_by_path(parsed: Sequence[ParseResult], roots: dict[str, str]) -> dict[str, str]:
    mapping = {}
    for result in parsed:
        key = result.nodes[0].attrs.get("package_key")
        mapping[result.path] = roots.get(key, "") if isinstance(key, str) else ""
    return mapping

