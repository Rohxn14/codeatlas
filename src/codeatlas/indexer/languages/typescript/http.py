"""HTTP client calls: `fetch`, `axios` and axios instances made with `axios.create`.

An instance is often created in one file (`export const http = axios.create({baseURL})`)
and used in another (`import { http } from "./http"; http.post("/users")`). An adapter
sees one file, so it records both halves and the HTTP linker joins them:

- the creating module lists its exported instances in its module node's attrs
  (`axios_instances`, see `exported_instances`);
- a call through an imported name is emitted with client `axios:<local name>` and the
  URL as written, for the linker to prefix with the instance's base URL.
"""

from __future__ import annotations

from dataclasses import dataclass

from tree_sitter import Node as TSNode

from codeatlas.indexer.languages.typescript import syntax
from codeatlas.indexer.languages.typescript.symbols import Symbols
from codeatlas.indexer.linker.urls import IMPORTED_AXIOS, join_client_url
from codeatlas.indexer.linker.urls import join_url as join_url  # re-exported for callers
from codeatlas.models import RawHttpCall, RawImport

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
        clients[syntax.text(name, source)] = _create_base(value, source)
    return clients


def _create_base(create_call: TSNode, source: bytes) -> ClientBase:
    """The `baseURL` given to `axios.create({...})`, empty when there is none."""
    args = syntax.arguments(create_call)
    base_url = (
        syntax.object_property(args[0], "baseURL", source)
        if args and args[0].type == "object"
        else None
    )
    base = syntax.expression_value(base_url, source) if base_url is not None else None
    return ClientBase(*base) if base else ClientBase()


def exported_instances(
    root: TSNode, source: bytes, clients: dict[str, ClientBase]
) -> dict[str, dict[str, str]]:
    """`{exported name: {"base_url", "url_kind"}}` for the module node's `axios_instances`.

    Covers `export const api = axios.create(...)`, `export default api`,
    `export default axios.create(...)` and `export { api, api as other }`.
    """
    exported: dict[str, ClientBase] = {}
    for node in syntax.walk(root):
        if node.type != "export_statement" or node.child_by_field_name("source") is not None:
            continue
        for child in node.named_children:
            if child.type in ("lexical_declaration", "variable_declaration"):
                exported.update(_declared_instances(child, source, clients))
            elif child.type == "export_clause":
                exported.update(_listed_instances(child, source, clients))
        value = node.child_by_field_name("value")
        base = _default_instance(value, source, clients) if value is not None else None
        if base is not None:
            exported["default"] = base
    return {k: {"base_url": v.text, "url_kind": v.kind} for k, v in exported.items()}


def _declared_instances(
    declaration: TSNode, source: bytes, clients: dict[str, ClientBase]
) -> dict[str, ClientBase]:
    """`export const api = axios.create(...)`: the instances among the declared names."""
    found = {}
    for declarator in declaration.named_children:
        name = declarator.child_by_field_name("name")
        local = syntax.text(name, source) if name is not None else ""
        if local in clients:
            found[local] = clients[local]
    return found


def _listed_instances(
    clause: TSNode, source: bytes, clients: dict[str, ClientBase]
) -> dict[str, ClientBase]:
    """`export { api, api as other }`: instances under their public names."""
    found = {}
    for spec in clause.named_children:
        name, alias = spec.child_by_field_name("name"), spec.child_by_field_name("alias")
        local = syntax.text(name, source) if name is not None else ""
        if local in clients and local != "axios":
            found[syntax.text(alias, source) if alias is not None else local] = clients[local]
    return found


def _default_instance(
    value: TSNode, source: bytes, clients: dict[str, ClientBase]
) -> ClientBase | None:
    """`export default api` (a local instance) or `export default axios.create(...)`."""
    if value.type == "identifier":
        name = syntax.text(value, source)
        return clients[name] if name in clients and name != "axios" else None
    if value.type == "call_expression":
        callee = value.child_by_field_name("function")
        if callee is not None and syntax.compact(callee, source) == "axios.create":
            return _create_base(value, source)
    return None


def imported_names(imports: tuple[RawImport, ...] | list[RawImport]) -> frozenset[str]:
    """Local names bound by an ES import or a destructuring `require`: each may be an
    axios instance exported by that module, which only the linker can confirm."""
    names = set()
    for raw in imports:
        if raw.is_reexport:
            continue
        names.update(alias or name for name, alias in raw.names)
    return frozenset(names)


def extract_http_calls(
    root: TSNode,
    source: bytes,
    symbols: Symbols,
    clients: dict[str, ClientBase],
    imported: frozenset[str] = frozenset(),
    route_lines: frozenset[int] = frozenset(),
) -> list[RawHttpCall]:
    """Requests made in this file.

    `imported` names (not shadowed by a local client) are candidate axios instances; a
    verb call on one is emitted as client `axios:<name>`, except on lines where the
    route extractor found an Express route (`router.get("/x", handler)`).
    """
    candidates = imported - clients.keys()
    found: list[RawHttpCall] = []
    for node in syntax.walk(root):
        if node.type != "call_expression":
            continue
        call = _fetch(node, source) or _axios(node, source, clients)
        if call is None and syntax.line(node) not in route_lines:
            call = _imported_instance(node, source, candidates)
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


def _imported_instance(call: TSNode, source: bytes, candidates: frozenset[str]) -> _Found | None:
    """`http.post("/users")` where `http` is imported: a possible axios instance."""
    callee = call.child_by_field_name("function")
    args = syntax.arguments(call)
    if callee is None or callee.type != "member_expression" or not args:
        return None
    obj, prop = callee.child_by_field_name("object"), callee.child_by_field_name("property")
    if obj is None or prop is None or obj.type != "identifier":
        return None
    name, method_name = syntax.text(obj, source), syntax.text(prop, source)
    if name not in candidates or method_name not in _AXIOS_METHODS:
        return None
    url = syntax.expression_value(args[0], source)
    return f"{IMPORTED_AXIOS}{name}", url, method_name.upper()


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
    """Join a client's base URL to a request URL (shared with the linker)."""
    return join_client_url(base.text, base.kind, *url)


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
