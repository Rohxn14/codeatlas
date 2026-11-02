"""IMPORTS and INHERITS edges: statements and class headers become module and class links."""

from __future__ import annotations

from codeatlas.indexer.languages.python.resolver.calls import EXTERNAL_PREFIX
from codeatlas.indexer.languages.python.resolver.names import Names, Ref, base_names
from codeatlas.indexer.languages.python.resolver.project import Project
from codeatlas.indexer.languages.python.resolver.tables import ModuleTable, module_paths
from codeatlas.models import (
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    RawImport,
    Resolution,
    make_node_id,
)


def import_edges(table: ModuleTable, names: Names, project: Project, snapshot: str) -> list[Edge]:
    """One edge per imported name (or per `import a.b`), from this file's module node.

    A name that may mean several files splits its confidence between them.
    """
    edges: list[Edge] = []
    for raw in table.imports:
        for candidates in _import_targets(table, raw, names, project):
            unique = list(dict.fromkeys(candidates))
            edges += [
                Edge(table.node.id, make_node_id(snapshot, key), EdgeKind.IMPORTS,
                     1.0 / len(unique), Resolution.STRUCTURAL, raw.line)
                for key in unique
            ]
    return edges


def _import_targets(
    table: ModuleTable, raw: RawImport, names: Names, project: Project
) -> list[list[str]]:
    """For each thing the statement imports, the keys it may mean."""
    paths = [p for p in module_paths(raw, table.path, table.package_root, project)
             if p in names.tables]
    if not paths:
        return [[key] for key in _outside(raw)]
    modules = [names.tables[p].node.key for p in paths]
    if not raw.names:
        return [modules]
    return [modules if name == "*" else [_target_key(p, name, names) for p in paths]
            for name, _alias in raw.names]


def _target_key(path: str, name: str, names: Names) -> str:
    """The symbol or submodule `name` of module `path`; the module itself for a variable."""
    ref = names.export(path, name, 3)
    if ref is not None and ref.kind == "node":
        return ref.nodes[0].key
    if ref is not None and ref.kind == "module" and ref.paths and ref.paths[0] in names.tables:
        return names.tables[ref.paths[0]].node.key
    return names.tables[path].node.key


def _outside(raw: RawImport) -> list[str]:
    """Targets outside the repository; a relative import that leaves it has none."""
    if raw.level:
        return []
    if not raw.names:
        return [EXTERNAL_PREFIX + raw.target]
    return [
        EXTERNAL_PREFIX + (raw.target if name == "*" else f"{raw.target}.{name}")
        for name, _ in raw.names
    ]


def inherit_edges(classes: list[Node], names: Names, snapshot: str) -> list[Edge]:
    """Each base that resolves to a repository class or an outside name."""
    edges: list[Edge] = []
    for cls in classes:
        for text in base_names(cls):
            ref = names.ref(cls.path, text) if text else None
            for key in _base_keys(ref):
                edges.append(Edge(
                    cls.id, make_node_id(snapshot, key), EdgeKind.INHERITS,
                    1.0 / max(1, len(_base_keys(ref))), Resolution.STRUCTURAL, cls.span.start_line,
                ))
    return edges


def _base_keys(ref: Ref | None) -> list[str]:
    if ref is None:
        return []
    if ref.kind == "external":
        return [EXTERNAL_PREFIX + ref.name]
    if ref.kind == "node":
        return [n.key for n in ref.nodes if n.kind in (NodeKind.CLASS, NodeKind.INTERFACE)]
    return []
