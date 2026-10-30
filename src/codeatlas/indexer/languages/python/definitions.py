"""Classes, functions and methods: qualnames, keys, signatures, decorators, docstrings.

The other extraction modules need two things from here: the list of definitions (for
nodes, tests and routes) and `Scopes`, which says which function a piece of code runs
in, so calls and HTTP calls get the right `caller_key`.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field

from tree_sitter import Node as TSNode

# T00's rule for repeated names (`#` + short hash of the signature, then an ordinal only
# for identical signatures). Reused, not copied, so a symbol keeps the same key whether
# the deep or the structural tier parses it. It is private to generic/adapter.py.
from codeatlas.indexer.generic.adapter import _Definition, _duplicate_suffixes
from codeatlas.indexer.languages.python.syntax import (
    NodeId,
    ident,
    one_line,
    string_value,
    text,
)
from codeatlas.models import NodeKind, make_key

_DEFINITION_TYPES = frozenset({"class_definition", "function_definition"})


@dataclass(slots=True)
class PyDefinition:
    """One class or function, filled in step by step before it becomes a Node."""

    node: TSNode  # the class_definition or function_definition
    outer: TSNode  # the decorated_definition around it, or the node itself
    name: str
    kind: NodeKind
    signature: str
    parent: PyDefinition | None
    decorators: list[TSNode] = field(default_factory=list)
    qualname: str = ""
    key: str = ""
    owner_key: str | None = None
    attrs: dict[str, object] = field(default_factory=dict)


def collect_definitions(root: TSNode, source: bytes, path: str) -> list[PyDefinition]:
    """Every class and function in source order, outer definitions before inner ones."""
    found: dict[NodeId, PyDefinition] = {}
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in _DEFINITION_TYPES:
            definition = _make_definition(node, source, found)
            if definition is not None:
                found[ident(node)] = definition
        stack.extend(reversed(node.children))
    definitions = list(found.values())
    _assign_keys(definitions, path)
    return definitions


def _make_definition(
    node: TSNode, source: bytes, found: dict[NodeId, PyDefinition]
) -> PyDefinition | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:  # only after a syntax error; the error is reported anyway
        return None
    wrapper = node.parent
    outer = wrapper if wrapper is not None and wrapper.type == "decorated_definition" else node
    is_class = node.type == "class_definition"
    definition = PyDefinition(
        node=node,
        outer=outer,
        name=text(name_node, source),
        kind=NodeKind.CLASS if is_class else NodeKind.FUNCTION,
        signature=signature(node, source),
        parent=_parent(node, found),
        decorators=[c for c in outer.children if c.type == "decorator"],
    )
    definition.attrs["decorators"] = [
        one_line(d, source).removeprefix("@").strip() for d in definition.decorators
    ]
    if is_class:
        definition.attrs["bases"] = _bases(node, source)
    else:
        definition.attrs["is_async"] = any(c.type == "async" for c in node.children)
    return definition


def _parent(node: TSNode, found: dict[NodeId, PyDefinition]) -> PyDefinition | None:
    current = node.parent
    while current is not None:
        if current.type in _DEFINITION_TYPES:
            return found.get(ident(current))
        current = current.parent
    return None


def signature(node: TSNode, source: bytes) -> str:
    """Source text from `def`/`class` (with `async`) up to the colon, whitespace collapsed.

    It stops at the colon token rather than at the body, so a comment after the colon
    (`def f():  # note`) is not part of the signature.
    """
    colon = next((c for c in node.children if c.type == ":"), None)
    body = node.child_by_field_name("body")
    end = colon.start_byte if colon is not None else (body.start_byte if body else node.end_byte)
    return " ".join(source[node.start_byte : end].decode("utf-8", "replace").split())


def _bases(node: TSNode, source: bytes) -> list[str]:
    """Base classes as written; keyword arguments such as `metaclass=` are not bases."""
    superclasses = node.child_by_field_name("superclasses")
    if superclasses is None:
        return []
    return [
        one_line(child, source)
        for child in superclasses.named_children
        if child.type not in ("keyword_argument", "comment")
    ]


def _assign_keys(definitions: list[PyDefinition], path: str) -> None:
    """Dotted qualnames from nesting, T00's suffix for repeated names, owners for methods."""
    t00 = {ident(d.node): _Definition(d.node, d.name, "", d.kind, d.signature) for d in definitions}
    parents = {ident(d.node): t00[ident(d.parent.node)] if d.parent else None for d in definitions}
    suffixes = _duplicate_suffixes(t00, parents, dict.fromkeys(t00))
    for definition in definitions:  # parents come first, so their qualname is ready
        parent = definition.parent
        base = f"{parent.qualname}.{definition.name}" if parent else definition.name
        definition.qualname = base + suffixes.get(ident(definition.node), "")
        definition.key = make_key(path, definition.qualname)
        if parent is not None and parent.kind is NodeKind.CLASS:
            definition.owner_key = parent.key


def docstring(body: TSNode | None, source: bytes) -> str | None:
    """The first statement of a block or module, if it is a plain string literal."""
    if body is None:
        return None
    first = next((c for c in body.named_children if c.type != "comment"), None)
    if first is None or first.type != "expression_statement" or first.named_child_count != 1:
        return None
    value = string_value(first.named_children[0], source)
    if value is None or value.is_fstring:  # an f-string is never a docstring
        return None
    return inspect.cleandoc(value.content) or None


class Scopes:
    """Answers "which function does this code run in?" for calls and HTTP calls.

    Code runs in a function only when it sits in that function's body. Decorators and
    default argument values run when the `def` statement runs, so they belong to the
    scope around the function; so does a class body, since a class is not a function.
    """

    def __init__(self, definitions: list[PyDefinition], module_key: str) -> None:
        self.module_key = module_key
        self._functions = {
            ident(d.node): d.key for d in definitions if d.node.type == "function_definition"
        }

    def caller_key(self, node: TSNode) -> str:
        child, parent = node, node.parent
        while parent is not None:
            if ident(parent) in self._functions:
                body = parent.child_by_field_name("body")
                if body is not None and ident(body) == ident(child):
                    return self._functions[ident(parent)]
            child, parent = parent, parent.parent
        return self.module_key
