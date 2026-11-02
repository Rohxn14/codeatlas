"""Import statements as written; the resolver (T06) turns them into edges.

Every form becomes one `RawImport` per imported module:

    import a.b              -> target "a.b"
    import a.b as c         -> target "a.b", alias "c"
    from . import x         -> target ".", level 1, names (("x", None),)
    from ..pkg import a as b -> target "..pkg", level 2, names (("a", "b"),)
    from x import *         -> target "x", names (("*", None),)

Imports anywhere in the file count (inside functions, `try` or `if TYPE_CHECKING`).
"""

from __future__ import annotations

from tree_sitter import Node as TSNode

from codeatlas.indexer.languages.python.syntax import line, text, walk
from codeatlas.models import RawImport

Names = tuple[tuple[str, str | None], ...]


def collect_imports(root: TSNode, source: bytes, module_key: str) -> list[RawImport]:
    imports: list[RawImport] = []
    for node in walk(root):
        if node.type == "import_statement":
            imports.extend(_plain_imports(node, source, module_key))
        elif node.type == "import_from_statement":
            imports.append(_from_import(node, source, module_key))
        elif node.type == "future_import_statement":
            names = tuple(_name_and_alias(n, source) for n in node.children_by_field_name("name"))
            imports.append(RawImport(module_key, "__future__", names, line=line(node)))
    return imports


def _plain_imports(node: TSNode, source: bytes, module_key: str) -> list[RawImport]:
    """`import a, b.c as d` imports two modules, so it gives two RawImports."""
    found = []
    for name_node in node.children_by_field_name("name"):
        target, alias = _name_and_alias(name_node, source)
        found.append(RawImport(module_key, target, alias=alias, line=line(node)))
    return found


def _from_import(node: TSNode, source: bytes, module_key: str) -> RawImport:
    module = node.child_by_field_name("module_name")
    target = "".join(text(module, source).split()) if module is not None else ""
    level = len(target) - len(target.lstrip("."))
    names: Names
    if any(c.type == "wildcard_import" for c in node.children):
        names = (("*", None),)
    else:
        names = tuple(_name_and_alias(n, source) for n in node.children_by_field_name("name"))
    return RawImport(module_key, target, names, level=level, line=line(node))


def _name_and_alias(node: TSNode, source: bytes) -> tuple[str, str | None]:
    if node.type == "aliased_import":
        name, alias = node.child_by_field_name("name"), node.child_by_field_name("alias")
        return (
            text(name, source) if name is not None else "",
            text(alias, source) if alias is not None else None,
        )
    return text(node, source), None
