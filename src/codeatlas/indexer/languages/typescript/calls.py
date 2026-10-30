"""Calls as written: function calls, `new` expressions and capitalised JSX elements."""

from __future__ import annotations

from tree_sitter import Node as TSNode

from codeatlas.indexer.languages.typescript import syntax
from codeatlas.indexer.languages.typescript.imports import is_module_call
from codeatlas.indexer.languages.typescript.symbols import Symbols
from codeatlas.models import RawCall

_JSX_TAGS = frozenset({"jsx_self_closing_element", "jsx_opening_element"})
# Callee shapes with a readable name; `a()()` or `(x || y)()` have none and are skipped.
_NAMED_CALLEES = frozenset({"identifier", "member_expression"})


def extract_calls(root: TSNode, source: bytes, symbols: Symbols) -> list[RawCall]:
    calls: list[RawCall] = []
    for node in syntax.walk(root):
        callee: TSNode | None = None
        if node.type == "call_expression" and not is_module_call(node, source):
            callee = node.child_by_field_name("function")
        elif node.type == "new_expression":
            callee = node.child_by_field_name("constructor")
        elif node.type in _JSX_TAGS:
            callee = _component(node, source)
        if callee is None or callee.type not in _NAMED_CALLEES:
            continue
        name, receiver = _split(callee, source)
        calls.append(
            RawCall(
                caller_key=symbols.caller_key(node),
                callee_text=callee_text(callee, source),
                name=name,
                receiver=receiver,
                line=syntax.line(node),
            )
        )
    return calls


def _component(element: TSNode, source: bytes) -> TSNode | None:
    """`<UserCard />` renders the component `UserCard`; `<div>` is a plain HTML tag."""
    name = element.child_by_field_name("name")
    if name is None or not syntax.text(name, source)[:1].isupper():
        return None
    return name


def _split(callee: TSNode, source: bytes) -> tuple[str, str | None]:
    """`this.repo.save` -> (`save`, `this.repo`); `fetchUser` -> (`fetchUser`, None)."""
    if callee.type == "member_expression":
        prop, obj = callee.child_by_field_name("property"), callee.child_by_field_name("object")
        if prop is not None and obj is not None:
            return syntax.text(prop, source), callee_text(obj, source)
    return syntax.text(callee, source), None


def callee_text(node: TSNode, source: bytes) -> str:
    """The callee as written, with the arguments of calls inside it shortened to `(...)`.

    `fetch(url).then` keeps its shape without dragging a callback's whole body into
    the text: `router.route("/x").get((req, res) => ...).post` becomes
    `router.route(...).get(...).post`.
    """
    if node.type == "call_expression":
        inner = node.child_by_field_name("function")
        if inner is not None:
            return callee_text(inner, source) + "(...)"
    if node.type == "member_expression":
        obj, prop = node.child_by_field_name("object"), node.child_by_field_name("property")
        if obj is not None and prop is not None:
            dot = "?." if node.child_by_field_name("optional_chain") is not None else "."
            return callee_text(obj, source) + dot + syntax.text(prop, source)
    return syntax.compact(node, source)
