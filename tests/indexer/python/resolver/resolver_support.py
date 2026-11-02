"""Helpers: parse sample files, load them into an in-memory store, run the resolver."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from codeatlas.indexer.languages.python.adapter import PythonAdapter
from codeatlas.indexer.languages.python.resolver import PythonResolver
from codeatlas.models import Edge, Node, NodeKind, Snapshot, Span, make_node_id
from codeatlas.store import GraphStore

SNAPSHOT = "demo@0123456789ab"
DATA = Path(__file__).parents[3] / "data" / "python_resolver"

# kind, source key, target key, resolution, confidence, line
Row = tuple[str, str, str, str, float, int | None]


def load_tree(name: str) -> dict[str, str]:
    """Every .py file under tests/data/python_resolver/<name>, keyed by repo-relative path."""
    root = DATA / name
    return {p.relative_to(DATA).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(root.rglob("*.py"))}


def _package(root: str, name: str) -> Node:
    key = f"{root}/pyproject.toml::package:{name}" if root else f"pyproject.toml::package:{name}"
    return Node(make_node_id(SNAPSHOT, key), key, SNAPSHOT, NodeKind.PACKAGE, "python", name,
                "", key.split("::")[0], Span(1, 1), attrs={"root": root})


def run_resolver(files: dict[str, str], packages: dict[str, str] | None = None) -> list[Row]:
    """Resolve `files`; `packages` maps a package root folder to a name (T15's output)."""
    adapter = PythonAdapter()
    results = [adapter.parse(path, text.encode(), SNAPSHOT) for path, text in files.items()]
    package_nodes = {root: _package(root, name) for root, name in (packages or {}).items()}
    fixed = []
    for result in results:
        owner = max((r for r in package_nodes if r and result.path.startswith(r + "/")),
                    key=len, default=None)
        if owner is not None:
            module = result.nodes[0]
            attrs = {**module.attrs, "package_key": package_nodes[owner].key}
            result = replace(result, nodes=(replace(module, attrs=attrs), *result.nodes[1:]))
        fixed.append(result)
    with GraphStore(":memory:") as store:
        snapshot = Snapshot(SNAPSHOT, "demo", "0" * 40, "2026-11-02T00:00:00Z", "t", "t")
        store.create_snapshot(snapshot)
        store.write_nodes([*package_nodes.values(), *(n for r in fixed for n in r.nodes)])
        edges = PythonResolver().resolve(fixed, store.symbol_index(SNAPSHOT))
    return sorted(_row(e) for e in edges)


def _row(edge: Edge) -> Row:
    cut = len(SNAPSHOT) + 1
    return (str(edge.kind), edge.src_id[cut:], edge.dst_id[cut:], str(edge.resolution),
            round(edge.confidence, 3), edge.line)


def of_kind(rows: list[Row], kind: str) -> list[Row]:
    return [r for r in rows if r[0] == kind]
