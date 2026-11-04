"""Definitions: classes, interfaces, functions, methods and tests, with their keys.

The walk records each definition with its parent definition and a *local* name; keys
are assigned afterwards, outer first, so a repeated name can get T00's signature-hash
suffix before its children's qualnames are built from it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from tree_sitter import Node as TSNode

from codeatlas.indexer.generic.adapter import _Definition, _duplicate_suffixes
from codeatlas.indexer.languages.typescript import syntax
from codeatlas.indexer.languages.typescript.syntax import NodeId, ident
from codeatlas.models import Node, NodeKind, Span, make_key, make_node_id

CLASS_TYPES = frozenset({"class_declaration", "abstract_class_declaration"})
FUNCTION_DECLARATIONS = frozenset({"function_declaration", "generator_function_declaration"})
FUNCTION_VALUES = frozenset({"arrow_function", "function_expression", "function"})
_DECLARATION_LISTS = frozenset({"lexical_declaration", "variable_declaration"})

# Test runners: Jest, Vitest, Mocha and Jasmine spellings, plus their modifiers.
_SUITE_CALLS = frozenset({"describe", "context", "suite", "fdescribe", "xdescribe"})
_TEST_CALLS = frozenset({"it", "test", "fit", "xit", "xtest"})
_TEST_MODIFIERS = frozenset({"only", "skip", "concurrent", "todo", "failing"})
_TEST_SEPARATOR = " > "
_TEST_FOLDERS = frozenset({"__tests__", "test", "tests", "spec"})
_CALLER_KINDS = frozenset({NodeKind.FUNCTION, NodeKind.TEST})


@dataclass(slots=True)
class Definition:
    node: TSNode  # the node whose descendants belong to this definition
    kind: NodeKind
    local_name: str  # name within the parent; for a test, its describe path too
    name: str
    parent: Definition | None
    span: Span
    signature: str | None = None
    docstring: str | None = None
    attrs: dict[str, object] = field(default_factory=dict)
    qualname: str = ""


def is_test_file(path: str) -> bool:
    """`*.test.*`, `*.spec.*`, or anything under a `__tests__`, `test`, `tests` or `spec`
    folder.

    Mocha projects (express, lodash) keep `describe`/`it` files in `test/` with plain
    names. Missing them left every call inside `it(...)` callbacks at module level, so
    the acceptance suite showed express with 99% of calls unresolved.
    """
    pure = PurePosixPath(path)
    stem_parts = pure.name.split(".")[1:-1]
    folders = {part.lower() for part in pure.parts[:-1]}
    return bool(folders & _TEST_FOLDERS) or "test" in stem_parts or "spec" in stem_parts


class Symbols:
    """All definitions in one file, and which one encloses any given tree node."""

    def __init__(self, root: TSNode, source: bytes, path: str) -> None:
        self.path = path
        self.module_key = make_key(path, "")
        walker = _Walker(source, exported_names(root, source), is_test_file(path))
        walker.visit(root)
        self.definitions = walker.found
        _assign_qualnames(self.definitions)
        self._by_node = {ident(d.node): d for d in self.definitions}

    def key(self, definition: Definition) -> str:
        return make_key(self.path, definition.qualname)

    def caller_key(self, node: TSNode) -> str:
        """Innermost named function, method or test around `node`, else the module key.

        Anonymous callbacks are not definitions, so their calls fall through to the
        named function that contains them. The search starts at the parent, so the
        `it(...)` call that defines a test belongs to the scope around the test.
        """
        parent = node.parent
        while parent is not None:
            found = self._by_node.get(ident(parent))
            if found is not None and found.kind in _CALLER_KINDS:
                return self.key(found)
            parent = parent.parent
        return self.module_key

    def function_key(self, name: str) -> str | None:
        """Key of a function defined at module level under `name`, for route handlers."""
        for definition in self.definitions:
            top_level = definition.parent is None and definition.kind is NodeKind.FUNCTION
            if top_level and definition.local_name == name:
                return self.key(definition)
        return None

    def nodes(self, language: str, snapshot_id: str) -> list[Node]:
        nodes = []
        for definition in self.definitions:
            key = self.key(definition)
            parent = definition.parent
            owner = parent if parent is not None and parent.kind is NodeKind.CLASS else None
            nodes.append(
                Node(
                    id=make_node_id(snapshot_id, key),
                    key=key,
                    snapshot_id=snapshot_id,
                    kind=definition.kind,
                    language=language,
                    name=definition.name,
                    qualname=definition.qualname,
                    path=self.path,
                    span=definition.span,
                    signature=definition.signature,
                    docstring=definition.docstring,
                    owner_key=self.key(owner) if owner else None,
                    attrs=definition.attrs,
                )
            )
        return nodes


def _assign_qualnames(definitions: list[Definition]) -> None:
    """Qualnames outer first, with T00's `#hash` suffix where a name repeats in a scope."""
    generic = {
        ident(d.node): _Definition(d.node, d.local_name, "", d.kind, d.signature)
        for d in definitions
    }
    parents = {
        ident(d.node): generic[ident(d.parent.node)] if d.parent else None for d in definitions
    }
    owners: dict[NodeId, str | None] = dict.fromkeys(generic)
    suffixes = _duplicate_suffixes(generic, parents, owners)
    for definition in definitions:  # the walk appends parents before their children
        own = definition.local_name + suffixes.get(ident(definition.node), "")
        parent = definition.parent
        definition.qualname = f"{parent.qualname}.{own}" if parent else own
        if definition.kind is NodeKind.TEST:
            # The runner's own id: a repeated test name gets no hash suffix there.
            local = definition.local_name
            definition.attrs["test_id"] = f"{parent.qualname}.{local}" if parent else local


@dataclass(frozen=True, slots=True)
class _Context:
    parent: Definition | None = None
    suites: tuple[str, ...] = ()


class _Walker:
    """One pass over the tree; each handler returns the context for the node's children."""

    def __init__(self, source: bytes, exported: frozenset[str], test_file: bool) -> None:
        self.source = source
        self.exported = exported
        self.test_file = test_file
        self.found: list[Definition] = []

    def visit(self, root: TSNode) -> None:
        stack: list[tuple[TSNode, _Context]] = [(root, _Context())]
        while stack:
            node, context = stack.pop()
            inner = self._handle(node, context)
            stack.extend((child, inner) for child in reversed(node.named_children))

    def _handle(self, node: TSNode, context: _Context) -> _Context:
        kind = node.type
        if kind in CLASS_TYPES or (kind == "class" and _is_default_export(node)):
            return self._class(node, context)
        if kind == "class" and self._name(node) and not _bound_by_declarator(node):
            # A named class expression: `module.exports = class Repo extends Base {}`.
            return self._class(node, context)
        if kind == "interface_declaration":
            self._interface(node, context)
        elif kind in FUNCTION_DECLARATIONS:
            return self._function_declaration(node, context)
        elif kind == "method_definition" and _in_class(node, context):
            return self._method(node, context)
        elif kind == "variable_declarator" and _at_module_level(node):
            return self._module_variable(node, context)
        elif kind in FUNCTION_VALUES and _is_default_export(node):
            return self._default_export(node, context)
        elif kind == "call_expression" and self.test_file:
            return self._test_call(node, context)
        return context

    def _add(self, definition: Definition) -> _Context:
        self.found.append(definition)
        return _Context(definition)

    def _is_exported(self, statement: TSNode, name: str) -> bool:
        return statement.type == "export_statement" or name in self.exported

    # Classes and interfaces

    def _class(self, node: TSNode, context: _Context, name: str | None = None) -> _Context:
        name = name or self._name(node) or ("default" if _is_default_export(node) else None)
        if name is None:
            return context
        statement = _statement(node)
        body = node.child_by_field_name("body")
        first = next((c for c in node.children if c.type != "decorator"), node)
        attrs: dict[str, object] = {
            "bases": _class_bases(node, self.source),
            "decorators": _decorators(_decorator_nodes(node, statement), self.source),
            "exported": self._is_exported(statement, name),
        }
        fields = _class_fields(body, self.source) if body is not None else {}
        if fields:
            attrs["fields"] = fields
        return self._add(
            Definition(
                node,
                NodeKind.CLASS,
                name,
                name,
                context.parent,
                syntax.span(node),
                _signature_from(first, node, body, self.source),
                syntax.jsdoc(statement, self.source),
                attrs,
            )
        )

    def _interface(self, node: TSNode, context: _Context) -> None:
        name = self._name(node)
        if name is None:
            return
        statement = _statement(node)
        bases = [
            syntax.text(child, self.source)
            for clause in node.named_children
            if clause.type == "extends_type_clause"
            for child in clause.named_children
        ]
        attrs: dict[str, object] = {"bases": bases, "exported": self._is_exported(statement, name)}
        self._add(
            Definition(
                node,
                NodeKind.INTERFACE,
                name,
                name,
                context.parent,
                syntax.span(node),
                syntax.signature(node, node.child_by_field_name("body"), self.source),
                syntax.jsdoc(statement, self.source),
                attrs,
            )
        )

    # Functions

    def _function_declaration(self, node: TSNode, context: _Context) -> _Context:
        name = self._name(node) or ("default" if _is_default_export(node) else None)
        if name is None:
            return context
        statement = _statement(node)
        exported = context.parent is None and self._is_exported(statement, name)
        return self._function(node, node, name, name, context, statement, exported)

    def _default_export(self, node: TSNode, context: _Context) -> _Context:
        """`export default () => ...` or `export default function () {}`: named `default`."""
        statement = _statement(node)
        return self._function(node, statement, "default", "default", context, statement, True)

    def _method(self, node: TSNode, context: _Context) -> _Context:
        owner = context.parent
        assert owner is not None  # _in_class checked it
        name = self._name(node) or syntax.text(node, self.source)
        attrs = {"decorators": _decorators(_preceding_decorators(node), self.source)}
        doc_anchor = _first_preceding_decorator(node)
        return self._function(
            node, node, name, name, context, doc_anchor, bool(owner.attrs.get("exported")), attrs
        )

    def _module_variable(self, node: TSNode, context: _Context) -> _Context:
        """`const f = () => ...`, `const f = function ...`, or an exported object of methods."""
        name_node, value = node.child_by_field_name("name"), node.child_by_field_name("value")
        if name_node is None or value is None or name_node.type != "identifier":
            return context
        name = syntax.text(name_node, self.source)
        declaration = node.parent
        statement = _statement(declaration)
        exported = self._is_exported(statement, name)
        if value.type in FUNCTION_VALUES:
            # One declarator: the span and signature start at `const`; else at the name.
            single = len(declaration.named_children) == 1
            start = declaration if single else node
            return self._function(
                node, start, name, name, context, statement, exported, span_node=start
            )
        if value.type == "class":  # `const Svc = class {}`: named by its variable
            return self._class(value, context, name)
        if value.type == "object" and exported:
            self._object_methods(value, name, context)
        return context

    def _object_methods(self, obj: TSNode, object_name: str, context: _Context) -> None:
        """Methods of an exported object literal become `object.method` functions.

        The object is not a node, so the parent stays the module; the methods are added
        here and the walk then descends into them through `_handle` for their calls.
        """
        for member in obj.named_children:
            if member.type == "method_definition":
                name_node, target = member.child_by_field_name("name"), member
            elif member.type == "pair":
                value = member.child_by_field_name("value")
                if value is None or value.type not in FUNCTION_VALUES:
                    continue
                name_node, target = member.child_by_field_name("key"), member
            else:
                continue
            if name_node is None:
                continue
            name = syntax.text(name_node, self.source).strip("'\"")
            self._function(target, target, name, f"{object_name}.{name}", context, target, True)

    def _function(
        self,
        node: TSNode,
        start: TSNode,
        name: str,
        local_name: str,
        context: _Context,
        doc_anchor: TSNode,
        exported: bool,
        attrs: dict[str, object] | None = None,
        span_node: TSNode | None = None,
    ) -> _Context:
        function = _function_part(node)
        body = function.child_by_field_name("body")
        attrs = dict(attrs or {})
        attrs["is_async"] = syntax.has_token(function, "async")
        attrs["exported"] = exported
        return self._add(
            Definition(
                node,
                NodeKind.FUNCTION,
                local_name,
                name,
                context.parent,
                syntax.span(span_node or node),
                syntax.signature(start, body, self.source),
                syntax.jsdoc(doc_anchor, self.source),
                attrs,
            )
        )

    # Tests

    def _test_call(self, node: TSNode, context: _Context) -> _Context:
        role = _test_role(node.child_by_field_name("function"), self.source)
        if role is None:
            return context
        args = syntax.arguments(node)
        title = syntax.literal_string(args[0], self.source) if args else None
        if title is None:
            return context
        if role == "suite":
            return _Context(context.parent, (*context.suites, title))
        local_name = _TEST_SEPARATOR.join((*context.suites, title))
        definition = Definition(
            node, NodeKind.TEST, local_name, title, context.parent, syntax.span(node)
        )
        return _Context(self._add(definition).parent, context.suites)

    def _name(self, node: TSNode) -> str | None:
        name = node.child_by_field_name("name")
        return syntax.text(name, self.source) if name is not None else None


# Shape helpers


def _statement(node: TSNode) -> TSNode:
    """The export statement wrapping a declaration, where its JSDoc sits, else the node."""
    parent = node.parent
    return parent if parent is not None and parent.type == "export_statement" else node


def _function_part(node: TSNode) -> TSNode:
    """The node holding `async`, the parameters and the body, whatever wraps it."""
    if node.type == "variable_declarator":
        return node.child_by_field_name("value") or node
    if node.type == "pair":
        return node.child_by_field_name("value") or node
    return node


def _at_module_level(declarator: TSNode) -> bool:
    declaration = declarator.parent
    if declaration is None or declaration.type not in _DECLARATION_LISTS:
        return False
    holder = _statement(declaration).parent
    return holder is not None and holder.type == "program"


def _is_default_export(node: TSNode) -> bool:
    parent = node.parent
    return (
        parent is not None
        and parent.type == "export_statement"
        and syntax.has_token(parent, "default")
    )


def _in_class(node: TSNode, context: _Context) -> bool:
    parent = node.parent
    return (
        parent is not None
        and parent.type == "class_body"
        and context.parent is not None
        and context.parent.kind is NodeKind.CLASS
    )


def _signature_from(first: TSNode, node: TSNode, body: TSNode | None, source: bytes) -> str | None:
    """Like `syntax.signature`, but starting after the decorators at `first`."""
    end = body.start_byte if body is not None else node.end_byte
    raw = source[first.start_byte : end].decode("utf-8", "replace")
    return " ".join(raw.split()).rstrip("{ ").strip() or None


def _class_bases(node: TSNode, source: bytes) -> list[str]:
    """`extends` and `implements` targets as written; JS puts the expression directly."""
    bases: list[str] = []
    for heritage in node.named_children:
        if heritage.type != "class_heritage":
            continue
        for clause in heritage.named_children:
            if clause.type == "extends_clause":
                value = clause.child_by_field_name("value")
                if value is not None:
                    end = clause.end_byte
                    text = source[value.start_byte : end].decode("utf-8", "replace")
                    bases.append(" ".join(text.split()))
            elif clause.type == "implements_clause":
                bases.extend(syntax.text(t, source) for t in clause.named_children)
            elif clause.type != "comment":  # JavaScript: `extends Base`
                bases.append(" ".join(syntax.text(clause, source).split()))
    return bases


_FIELD_TYPES = frozenset({"public_field_definition", "field_definition"})
_JSDOC_TYPE = re.compile(r"@type\s*\{([^}]*)\}")


def _class_fields(body: TSNode, source: bytes) -> dict[str, str]:
    """Field name -> declared type text, for the resolver's `this.repo.save()` (T20).

    The type is the annotation, else a JSDoc `@type`, else the class of a `new X()`
    initialiser; a field with none of these is left out. Assignments in the constructor
    (`this.repo = new UserRepo()`) count too, after the declarations.
    """
    fields: dict[str, str] = {}
    for member in body.named_children:
        if member.type in _FIELD_TYPES:
            name = member.child_by_field_name("name") or member.child_by_field_name("property")
            if name is not None:
                annotation = member.child_by_field_name("type")
                written = syntax.text(annotation, source).lstrip(":") if annotation else None
                found = _field_type(written, member, member.child_by_field_name("value"), source)
                if found:
                    fields.setdefault(syntax.text(name, source), found)
        elif member.type == "method_definition" and _is_constructor(member, source):
            _constructor_fields(member, source, fields)
    return fields


def _constructor_fields(ctor: TSNode, source: bytes, fields: dict[str, str]) -> None:
    body = ctor.child_by_field_name("body")
    for node in syntax.walk(body) if body is not None else ():
        if node.type != "assignment_expression" or node.parent is None:
            continue
        left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
        target = left.child_by_field_name("object") if left is not None else None
        prop = left.child_by_field_name("property") if left is not None else None
        if target is None or prop is None or target.type != "this":
            continue
        name, found = syntax.text(prop, source), _field_type(None, node.parent, right, source)
        if found:  # an untyped `this.x = x` adds nothing
            fields.setdefault(name, found)


def _field_type(
    annotation: str | None, anchor: TSNode, value: TSNode | None, source: bytes
) -> str:
    if annotation:
        return " ".join(annotation.split())
    doc = syntax.jsdoc(anchor, source)
    match = _JSDOC_TYPE.search(doc) if doc else None
    if match:
        return match.group(1).strip()
    if value is not None and value.type == "new_expression":
        constructor = value.child_by_field_name("constructor")
        if constructor is not None and constructor.type in ("identifier", "member_expression"):
            return syntax.compact(constructor, source)
    return ""


def _is_constructor(method: TSNode, source: bytes) -> bool:
    name = method.child_by_field_name("name")
    return name is not None and syntax.text(name, source) == "constructor"


def _decorator_nodes(node: TSNode, statement: TSNode) -> list[TSNode]:
    """Class decorators sit on the class, or on `export` when written before it."""
    own = [c for c in node.children if c.type == "decorator"]
    outer = [c for c in statement.children if c.type == "decorator"] if statement != node else []
    return outer + own


def _preceding_decorators(node: TSNode) -> list[TSNode]:
    found: list[TSNode] = []
    current = node.prev_named_sibling
    while current is not None and current.type == "decorator":
        found.insert(0, current)
        current = current.prev_named_sibling
    return found


def _first_preceding_decorator(node: TSNode) -> TSNode:
    decorators = _preceding_decorators(node)
    return decorators[0] if decorators else node


def _decorators(nodes: list[TSNode], source: bytes) -> list[str]:
    return [" ".join(syntax.text(n, source).removeprefix("@").split()) for n in nodes]


def _test_role(callee: TSNode | None, source: bytes) -> str | None:
    """ "suite" for describe-like calls, "test" for it/test, None otherwise."""
    if callee is None:
        return None
    if callee.type == "member_expression":
        prop = callee.child_by_field_name("property")
        if prop is None or syntax.text(prop, source) not in _TEST_MODIFIERS:
            return None
        callee = callee.child_by_field_name("object")
    if callee is None or callee.type != "identifier":
        return None
    name = syntax.text(callee, source)
    if name in _SUITE_CALLS:
        return "suite"
    return "test" if name in _TEST_CALLS else None


# Exports


def exported_names(root: TSNode, source: bytes) -> frozenset[str]:
    """Local names exported by a separate statement: `export {a}`, `module.exports = ...`.

    Declarations written with `export` in front are recognised where they are declared.
    """
    names: set[str] = set()
    for statement in root.named_children:
        if statement.type == "export_statement":
            names.update(_export_statement_names(statement, source))
        elif statement.type == "expression_statement":
            names.update(_commonjs_names(statement, source))
    return frozenset(names)


def _export_statement_names(statement: TSNode, source: bytes) -> set[str]:
    if statement.child_by_field_name("source") is not None:
        return set()  # a re-export names another module's symbols
    names: set[str] = set()
    for child in statement.named_children:
        if child.type == "export_clause":
            for spec in child.named_children:
                name = spec.child_by_field_name("name")
                if name is not None:
                    names.add(syntax.text(name, source))
        elif child.type == "identifier":  # export default name
            names.add(syntax.text(child, source))
    return names


def _commonjs_names(statement: TSNode, source: bytes) -> set[str]:
    """`module.exports = name`, `module.exports = {a, b: c}`, `exports.x = name`."""
    assignment = statement.named_children[0] if statement.named_children else None
    if assignment is None or assignment.type != "assignment_expression":
        return set()
    left, right = assignment.child_by_field_name("left"), assignment.child_by_field_name("right")
    if left is None or right is None:
        return set()
    target = syntax.compact(left, source)
    if not (target == "module.exports" or target.startswith(("exports.", "module.exports."))):
        return set()
    if right.type == "identifier":
        return {syntax.text(right, source)}
    if right.type != "object" or target != "module.exports":
        return set()
    names: set[str] = set()
    for member in right.named_children:
        if member.type == "shorthand_property_identifier":
            names.add(syntax.text(member, source))
        elif member.type == "pair":
            value = member.child_by_field_name("value")
            if value is not None and value.type == "identifier":
                names.add(syntax.text(value, source))
    return names


def _bound_by_declarator(node: TSNode) -> bool:
    """`const Svc = class X {}` is named by `_module_variable`; do not add it twice."""
    return node.parent is not None and node.parent.type == "variable_declarator"
