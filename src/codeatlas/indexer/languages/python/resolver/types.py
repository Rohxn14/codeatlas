"""Receiver types from what the code declares: annotations and constructor parameters.

The raw items carry no assignments, so the only evidence of a type is written in a
signature: `service: UserService`, `-> UserService`, or `__init__(self, repo: UserRepo)`
with the common `self.repo = repo` convention. Anything else stays unknown.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from codeatlas.indexer.languages.python.resolver.names import Names
from codeatlas.models import Node, NodeKind


@dataclass(frozen=True, slots=True)
class Signature:
    params: dict[str, str | None] = field(default_factory=dict)  # name -> annotation text
    returns: str | None = None


def parse_signature(text: str | None) -> Signature:
    """Parameter names with annotations and the return annotation; empty if unparsable."""
    if not text:
        return Signature()
    try:
        tree = ast.parse(text.strip() + ":\n    pass")
        func = tree.body[0]
    except SyntaxError:
        return Signature()
    if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
        return Signature()
    a = func.args
    every = [*a.posonlyargs, *a.args, *a.kwonlyargs, *filter(None, [a.vararg, a.kwarg])]
    params = {p.arg: ast.unparse(p.annotation) if p.annotation else None for p in every}
    return Signature(params, ast.unparse(func.returns) if func.returns else None)


def annotation_name(text: str | None) -> str | None:
    """The one class an annotation names: `X`, `"X"`, `X | None`, `Optional[X]`.

    Containers such as `list[X]` are not an `X`, so they give None.
    """
    if not text:
        return None
    try:
        node = ast.parse(text.strip().strip("'\""), mode="eval").body
    except SyntaxError:
        return None
    return _class_text(node)


def _class_text(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name | ast.Attribute):
        return ast.unparse(node)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return annotation_name(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        sides = [_class_text(side) for side in (node.left, node.right)]
        named = [s for s in sides if s and s != "None"]
        return named[0] if len(named) == 1 else None
    if isinstance(node, ast.Subscript) and ast.unparse(node.value).split(".")[-1] == "Optional":
        return _class_text(node.slice)
    return None


class Typer:
    """Turns annotations into repository classes."""

    def __init__(self, names: Names) -> None:
        self.names = names
        self._signatures: dict[str, Signature] = {}

    def signature(self, node: Node) -> Signature:
        cached = self._signatures.get(node.key)
        if cached is None:
            cached = self._signatures[node.key] = parse_signature(node.signature)
        return cached

    def annotated_class(self, path: str, annotation: str | None) -> Node | None:
        text = annotation_name(annotation)
        ref = self.names.ref(path, text) if text else None
        node = ref.nodes[0] if ref and ref.kind == "node" else None
        return node if node is not None and node.kind is NodeKind.CLASS else None

    def return_class(self, function: Node) -> Node | None:
        return self.annotated_class(function.path, self.signature(function).returns)

    def attribute_class(self, cls: Node, attr: str) -> Node | None:
        """Type of `self.attr`: an annotated `__init__` parameter of the same name.

        Looks in the class and its bases, nearest first, since a subclass usually
        inherits the constructor that stores the attribute.
        """
        for klass in self.names.mro(cls).classes:
            init = self.names.members_of.get(klass.key, {}).get("__init__")
            if init is None:
                continue
            annotation = self.signature(init).params.get(attr)
            found = self.annotated_class(init.path, annotation)
            if found is not None:
                return found
        return None
