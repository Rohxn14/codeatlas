"""HTTP client calls: `fetch`, `axios` and axios instances made with `axios.create`."""

from __future__ import annotations

from dataclasses import dataclass

from tree_sitter import Node as TSNode

from codeatlas.indexer.languages.typescript import syntax
from codeatlas.indexer.languages.typescript.symbols import Symbols
from codeatlas.models import RawHttpCall

_AXIOS_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


@dataclass(frozen=True, slots=True)
class ClientBase:
    """An axios client's base URL: empty for `axios` itself."""

    text: str = ""
    kind: str = syntax.LITERAL


def axios_clients(root: TSNode, source: bytes) -> dict[str, ClientBase]:
    """`axios` plus every `const api = axios.create({baseURL})` in the file."""
    clients = {"axios": ClientBase()}
    for node in syntax.walk(root):
        if node.type != "variable_declarator":
            continue
        name, value = node.child_by_field_name("name"), node.child_by_field_name("value")
        if name is None or value is None or value.type != "call_expression":
            continue
        callee = value.child_by_field_name("function")
        if callee is None or syntax.compact(callee, source) != "axios.create":
            continue
        args = syntax.arguments(value)
        base_url = (
            syntax.object_property(args[0], "baseURL", source)
            if args and args[0].type == "object"
            else None
        )
        base = syntax.expression_value(base_url, source) if base_url is not None else None
        clients[syntax.text(name, source)] = ClientBase(*base) if base else ClientBase()
    return clients


def extract_http_calls(
    root: TSNode, source: bytes, symbols: Symbols, clients: dict[str, ClientBase]
) -> list[RawHttpCall]:
    found: list[RawHttpCall] = []
    for node in syntax.walk(root):
        if node.type != "call_expression":
            continue
        call = _fetch(node, source) or _axios(node, source, clients)
        if call is None:
            continue
        client, url, method = call
        url_text, url_kind = url
        caller = symbols.caller_key(node)
        found.append(RawHttpCall(caller, client, url_text, url_kind, method, syntax.line(node)))
    return found


_Found = tuple[str, tuple[str, str], str | None]


def _fetch(call: TSNode, source: bytes) -> _Found | None:
    """`fetch(url, {method})`; with no `method` the request is a GET."""
    callee = call.child_by_field_name("function")
    if callee is None or syntax.text(callee, source) != "fetch":
        return None
    args = syntax.arguments(call)
    if not args:
        return None
    options = args[1] if len(args) > 1 else None
    return "fetch", syntax.expression_value(args[0], source), _method(options, source)


def _axios(call: TSNode, source: bytes, clients: dict[str, ClientBase]) -> _Found | None:
    """`axios.get(url)`, `api.post(url)`, `axios(url, config)` or `axios({url, method})`."""
    callee = call.child_by_field_name("function")
    args = syntax.arguments(call)
    if callee is None or not args:
        return None
    if callee.type == "identifier" and syntax.text(callee, source) in clients:
        base, method_name = clients[syntax.text(callee, source)], None
    elif callee.type == "member_expression":
        obj, prop = callee.child_by_field_name("object"), callee.child_by_field_name("property")
        if obj is None or prop is None or syntax.text(obj, source) not in clients:
            return None
        method_name = syntax.text(prop, source)
        if method_name not in _AXIOS_METHODS and method_name != "request":
            return None
        base = clients[syntax.text(obj, source)]
    else:
        return None
    if method_name in _AXIOS_METHODS:
        url, method = syntax.expression_value(args[0], source), method_name.upper()
    elif args[0].type == "object":  # axios({url, method}) or client.request({...})
        url_node = syntax.object_property(args[0], "url", source)
        if url_node is None:
            return None
        url, method = syntax.expression_value(url_node, source), _method(args[0], source)
    else:  # axios(url, config?)
        config = args[1] if len(args) > 1 else None
        url, method = syntax.expression_value(args[0], source), _method(config, source)
    return "axios", _prefixed(base, url), method


def _prefixed(base: ClientBase, url: tuple[str, str]) -> tuple[str, str]:
    """Join a client's base URL to a request URL.

    Strings and templates are joined as text (`/api` + `/users/${id}`). When either
    part is dynamic the result is an expression, so both are written as one:
    `"/api" + "/users/" + id`.
    """
    if not base.text:
        return url
    kind = syntax.worst_kind(base.kind, url[1])
    if kind != syntax.DYNAMIC:
        return join_url(base.text, url[0]), kind
    return f"{_expression(base.text, base.kind)} + {_expression(*url)}", kind


def join_url(base: str, path: str) -> str:
    """Join with exactly one `/`: `https://x.io/api/` + `/users` is `https://x.io/api/users`.

    An absolute request URL ignores the base, as axios does.
    """
    if not path:
        return base
    if path.startswith(("http://", "https://")):
        return path
    if base.endswith("/") and path.startswith("/"):
        return base + path[1:]
    if not base.endswith("/") and not path.startswith(("/", "?", "#")):
        return base + "/" + path
    return base + path


def _expression(text: str, kind: str) -> str:
    quote = {syntax.LITERAL: '"', syntax.TEMPLATE: "`"}.get(kind, "")
    return f"{quote}{text}{quote}"


def _method(options: TSNode | None, source: bytes) -> str | None:
    """The `method` in an options object: GET when absent, None when not a literal."""
    if options is None:
        return "GET"
    if options.type != "object":
        return None
    value = syntax.object_property(options, "method", source)
    if value is None:
        return "GET"
    literal = syntax.literal_string(value, source)
    return literal.upper() if literal else None
