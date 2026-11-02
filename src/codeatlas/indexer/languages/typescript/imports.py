"""Imports as written: ES modules, re-exports, CommonJS `require` and dynamic `import()`."""

from __future__ import annotations

from tree_sitter import Node as TSNode

from codeatlas.indexer.languages.typescript import syntax
from codeatlas.models import RawImport

Names = tuple[tuple[str, str | None], ...]


def extract_imports(root: TSNode, source: bytes, module_key: str) -> list[RawImport]:
    found: list[RawImport] = []
    for node in syntax.walk(root):
        if node.type == "import_statement":
            found.extend(_import_statement(node, source, module_key))
        elif node.type == "export_statement":
            found.extend(_reexport(node, source, module_key))
        elif node.type == "call_expression":
            found.extend(_call_import(node, source, module_key))
    return found


def is_module_call(call: TSNode, source: bytes) -> bool:
    """`require("x")` or `import("x")` with a literal: an import, so not also a call."""
    callee = call.child_by_field_name("function")
    if callee is None:
        return False
    if callee.type != "import" and not (
        callee.type == "identifier" and syntax.text(callee, source) == "require"
    ):
        return False
    args = syntax.arguments(call)
    return len(args) == 1 and syntax.literal_string(args[0], source) is not None


def _import_statement(node: TSNode, source: bytes, module_key: str) -> list[RawImport]:
    target = syntax.literal_string(node.child_by_field_name("source"), source)
    names: list[tuple[str, str | None]] = []
    alias: str | None = None
    for child in node.named_children:
        if child.type == "import_require_clause":  # TypeScript: import x = require("x")
            target = syntax.literal_string(child.child_by_field_name("source"), source)
            first = child.named_children[0] if child.named_children else None
            alias = syntax.text(first, source) if first and first.type == "identifier" else None
        elif child.type == "import_clause":
            alias = _import_clause(child, source, names)
    if target is None:
        return []
    return [RawImport(module_key, target, tuple(names), alias, line=syntax.line(node))]


def _import_clause(
    clause: TSNode, source: bytes, names: list[tuple[str, str | None]]
) -> str | None:
    """Fills `names`; returns the namespace alias of `* as ns`, if any."""
    alias = None
    for part in clause.named_children:
        if part.type == "identifier":
            names.append(("default", syntax.text(part, source)))
        elif part.type == "namespace_import":
            alias = _first_identifier(part, source)
        elif part.type == "named_imports":
            names.extend(_specifiers(part, source))
    return alias


def _reexport(node: TSNode, source: bytes, module_key: str) -> list[RawImport]:
    """`export {a} from "x"`, `export * from "x"`, `export * as ns from "x"`."""
    target = syntax.literal_string(node.child_by_field_name("source"), source)
    if target is None:
        return []
    names: Names = ()
    alias = None
    for child in node.named_children:
        if child.type == "export_clause":
            names = _specifiers(child, source)
        elif child.type == "namespace_export":
            alias = _first_identifier(child, source)
    return [RawImport(module_key, target, names, alias, is_reexport=True, line=syntax.line(node))]


def _call_import(call: TSNode, source: bytes, module_key: str) -> list[RawImport]:
    """`require("x")` or `import("x")` with a literal: bound to a name or a destructuring
    when it is, otherwise a plain whole-module import, wherever the call sits."""
    if not is_module_call(call, source):
        return []
    target = syntax.literal_string(syntax.arguments(call)[0], source)
    assert target is not None  # is_module_call checked it
    callee = call.child_by_field_name("function")
    holder = call.parent
    if callee is not None and callee.type == "import":
        return [RawImport(module_key, target, line=syntax.line(call))]
    if holder is not None and holder.type == "variable_declarator":
        name = holder.child_by_field_name("name")
        if name is not None and name.type == "identifier":
            alias = syntax.text(name, source)
            return [RawImport(module_key, target, alias=alias, line=syntax.line(call))]
        if name is not None and name.type == "object_pattern":
            names = _destructured(name, source)
            return [RawImport(module_key, target, names, line=syntax.line(call))]
    # Any other place (`require("x").config()`, `app.use(require("./routes"))`,
    # `module.exports = require("./x")`, `__importDefault(require("x"))`): still a
    # dependency on "x", just not bound to a name. Dropping it would lose the edge.
    return [RawImport(module_key, target, line=syntax.line(call))]


def _specifiers(node: TSNode, source: bytes) -> Names:
    """`{a, b as c}` in an import or export clause."""
    names: list[tuple[str, str | None]] = []
    for spec in node.named_children:
        name = spec.child_by_field_name("name")
        if name is None:
            continue
        alias = spec.child_by_field_name("alias")
        names.append(
            (syntax.text(name, source), syntax.text(alias, source) if alias is not None else None)
        )
    return tuple(names)


def _destructured(pattern: TSNode, source: bytes) -> Names:
    """`const {a, b: c} = require("x")` imports `a` and `b` (as `c`)."""
    names: list[tuple[str, str | None]] = []
    for part in pattern.named_children:
        if part.type == "shorthand_property_identifier_pattern":
            names.append((syntax.text(part, source), None))
        elif part.type == "pair_pattern":
            key, value = part.child_by_field_name("key"), part.child_by_field_name("value")
            if key is not None and value is not None and value.type == "identifier":
                names.append((syntax.text(key, source), syntax.text(value, source)))
    return tuple(names)


def _first_identifier(node: TSNode, source: bytes) -> str | None:
    for child in node.named_children:
        if child.type == "identifier":
            return syntax.text(child, source)
    return None
