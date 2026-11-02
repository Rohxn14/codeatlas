"""Per-file lookup tables built once from the parse results.

A `ModuleTable` answers "what does this name mean in this file?" for definitions and
imports. Import bindings are stored as written and resolved later, on demand, so a
re-export chain is followed only for names something actually asks about.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from codeatlas.indexer.languages.python.resolver.project import Project
from codeatlas.models import Node, NodeKind, ParseResult, RawImport

CALLABLE_KINDS = (NodeKind.FUNCTION, NodeKind.TEST)


@dataclass(frozen=True, slots=True)
class Binding:
    """What an imported local name stands for, before it is followed.

    `paths` are the repository files the import may mean (several when ambiguous);
    `external` is the dotted name when none matched (the target is outside the repo).
    `name` is the symbol taken from the module (`from m import name`), or None when the
    binding is the module itself (`import m`).
    """

    paths: tuple[str, ...]
    external: str | None
    name: str | None = None


@dataclass(slots=True)
class ModuleTable:
    path: str
    node: Node
    package_root: str = ""
    defs: dict[str, Node] = field(default_factory=dict)  # top-level qualname -> node
    # parent qualname -> {name: node}, for nested functions
    nested: dict[str, dict[str, Node]] = field(default_factory=dict)
    by_qualname: dict[str, Node] = field(default_factory=dict)
    bindings: dict[str, Binding] = field(default_factory=dict)
    star_imports: list[Binding] = field(default_factory=list)
    imports: list[RawImport] = field(default_factory=list)


def build_tables(
    results: list[ParseResult], project: Project, roots: dict[str, str]
) -> dict[str, ModuleTable]:
    """One table per file; `roots` maps a file path to its package root."""
    tables: dict[str, ModuleTable] = {}
    for result in results:
        if not result.nodes:
            continue
        table = ModuleTable(result.path, result.nodes[0], roots.get(result.path, ""))
        for node in result.nodes[1:]:
            _add_definition(table, node)
        tables[result.path] = table
    for result in results:
        table = tables.get(result.path)
        if table is not None:
            table.imports = list(result.imports)
            for raw in result.imports:
                _bind_import(table, raw, project)
    return tables


def _add_definition(table: ModuleTable, node: Node) -> None:
    """Index a node by qualname, and by plain name for lookups.

    Overloads and conditional redefinitions get a `#hash` suffix in their qualname; a
    caller writes only the plain name, and Python keeps the last definition, so the last
    one wins here too.
    """
    table.by_qualname[node.qualname] = node
    parent = node.qualname.rpartition(".")[0]
    if not parent:
        table.defs[node.name] = node
    else:
        table.nested.setdefault(parent, {})[node.name] = node


def module_paths(raw: RawImport, importer: str, own_root: str, project: Project) -> list[str]:
    """Repository files an import statement's module part may mean."""
    if raw.level:
        return project.relative_module(importer, raw.level, raw.target.lstrip("."))
    return project.find_module(raw.target, importer, own_root)


def _bind_import(table: ModuleTable, raw: RawImport, project: Project) -> None:
    paths = tuple(module_paths(raw, table.path, table.package_root, project))
    external = None if paths or raw.level else raw.target
    if not raw.names:
        _bind_plain(table, raw, paths, project)
        return
    for name, alias in raw.names:
        if name == "*":
            table.star_imports.append(Binding(paths, external))
            continue
        full = f"{external}.{name}" if external else None
        if not paths and full is None:
            continue  # a relative import that leaves the repository: nothing to bind
        table.bindings[alias or name] = Binding(paths, external, name)


def _bind_plain(
    table: ModuleTable, raw: RawImport, paths: tuple[str, ...], project: Project
) -> None:
    """`import a.b.c` binds `a`, `a.b` and `a.b.c`; `import a.b as x` binds only `x`."""
    if raw.alias:
        table.bindings[raw.alias] = Binding(paths, None if paths else raw.target)
        return
    parts = raw.target.split(".")
    for i in range(1, len(parts) + 1):
        dotted = ".".join(parts[:i])
        found = tuple(project.find_module(dotted, table.path, table.package_root))
        table.bindings.setdefault(dotted, Binding(found, None if found else dotted))

