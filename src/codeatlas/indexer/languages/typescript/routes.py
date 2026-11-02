"""Express routes: `app.get("/x", handler)` and `app.route("/x").get(...).post(...)`."""

from __future__ import annotations

import re

from tree_sitter import Node as TSNode

from codeatlas.indexer.languages.typescript import syntax
from codeatlas.indexer.languages.typescript.symbols import Symbols
from codeatlas.models import RawRoute

_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head", "all"})
# `:id` and `:id?` become `{id}`; a regex constraint such as `:id(\\d+)` is dropped.
_PARAM = re.compile(r":(\w+)(\([^)]*\))?\??")


def extract_routes(
    root: TSNode, source: bytes, symbols: Symbols, http_clients: frozenset[str]
) -> list[RawRoute]:
    """`http_clients` are names that are axios clients, whose `.get("/x", ...)` is a request."""
    routes: list[RawRoute] = []
    for node in syntax.walk(root):
        if node.type != "call_expression":
            continue
        route = _route(node, source, symbols, http_clients)
        if route is not None:
            routes.append(route)
    return routes


def normalise_path(path: str) -> str:
    return _PARAM.sub(lambda m: "{" + m.group(1) + "}", path)


def _route(
    call: TSNode, source: bytes, symbols: Symbols, http_clients: frozenset[str]
) -> RawRoute | None:
    callee = call.child_by_field_name("function")
    if callee is None or callee.type != "member_expression":
        return None
    prop, obj = callee.child_by_field_name("property"), callee.child_by_field_name("object")
    if prop is None or obj is None or syntax.text(prop, source) not in _METHODS:
        return None
    method = syntax.text(prop, source).upper()
    args = syntax.arguments(call)
    chained = _route_chain(obj, source)
    if chained is not None:  # app.route("/x").get(handler)
        router, path = chained
        handlers = args
    elif obj.type == "identifier" and syntax.text(obj, source) not in http_clients:
        router, path = syntax.text(obj, source), _path(args[0] if args else None, source)
        handlers = args[1:]
    else:
        return None
    if path is None or not handlers:
        return None
    return RawRoute(
        handler_key=_handler_key(handlers[-1], source, symbols),
        method="ANY" if method == "ALL" else method,
        path_pattern=normalise_path(path),
        framework="express",
        router=router,
        line=syntax.line(call),
    )


def _route_chain(obj: TSNode, source: bytes) -> tuple[str, str] | None:
    """Follow `.get(...).post(...)` back to `router.route("/x")`: (router, path)."""
    current: TSNode | None = obj
    while current is not None and current.type == "call_expression":
        callee = current.child_by_field_name("function")
        if callee is None or callee.type != "member_expression":
            return None
        prop, inner = callee.child_by_field_name("property"), callee.child_by_field_name("object")
        if prop is None or inner is None:
            return None
        name = syntax.text(prop, source)
        if name == "route" and inner.type == "identifier":
            args = syntax.arguments(current)
            path = _path(args[0] if args else None, source)
            return (syntax.text(inner, source), path) if path is not None else None
        if name not in _METHODS:
            return None
        current = inner
    return None


def _path(node: TSNode | None, source: bytes) -> str | None:
    """A route path is a literal starting with `/`; `app.get("title")` reads a setting."""
    value = syntax.literal_string(node, source)
    return value if value is not None and value.startswith("/") else None


def _handler_key(handler: TSNode, source: bytes, symbols: Symbols) -> str:
    """The named function in this file; otherwise (inline, imported) the module key."""
    if handler.type == "identifier":
        key = symbols.function_key(syntax.text(handler, source))
        if key is not None:
            return key
    return symbols.module_key
