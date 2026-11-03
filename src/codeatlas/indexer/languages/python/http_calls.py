"""Client HTTP requests made with requests or httpx, for the HTTP linker (T11).

Recognised forms:

    requests.get(url) / httpx.post(url, ...)       module-level helpers
    requests.request("GET", url)                   method given as an argument
    client.get(url)                                 `client` made from httpx.Client(),
                                                    httpx.AsyncClient(),
                                                    requests.Session() or a test client
                                                    (`TestClient(app)`, FastAPI and
                                                    Starlette) in the same function, or
                                                    at module level (by assignment or
                                                    `with ... as`)

The URL is `literal` for a plain string, `template` for an f-string or a
`"...".format(...)` call (the text inside the quotes is kept), `dynamic` otherwise
(the expression as written).
"""

from __future__ import annotations

from tree_sitter import Node as TSNode

from codeatlas.indexer.languages.python.definitions import Scopes
from codeatlas.indexer.languages.python.syntax import (
    argument,
    callee_parts,
    line,
    one_line,
    plain_string,
    string_value,
    text,
    walk,
)
from codeatlas.models import RawHttpCall

CLIENT_MODULES = frozenset({"requests", "httpx"})
HTTP_VERBS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})
_CLIENT_FACTORIES = {
    "httpx.Client": "httpx",
    "httpx.AsyncClient": "httpx",
    "requests.Session": "requests",
    "requests.session": "requests",
    # Test clients send requests to the app in-process; for the linker they are clients
    # like any other, and the calls in tests are the ones that cover the routes.
    "TestClient": "testclient",
    "testclient.TestClient": "testclient",
    "fastapi.testclient.TestClient": "testclient",
    "starlette.testclient.TestClient": "testclient",
}


def collect_http_calls(root: TSNode, source: bytes, scopes: Scopes) -> list[RawHttpCall]:
    clients = _client_variables(root, source, scopes)
    found = []
    for node in walk(root):
        if node.type != "call":
            continue
        parts = callee_parts(node, source)
        if parts is None or parts[2] is None:
            continue
        _, method_name, receiver = parts
        scope = scopes.caller_key(node)
        client = receiver if receiver in CLIENT_MODULES else _client_for(receiver, scope, clients)
        if client is None:
            continue
        http_call = _http_call(node, method_name, client, scope, source)
        if http_call is not None:
            found.append(http_call)
    return found


def _http_call(
    call: TSNode, method_name: str, client: str, scope: str, source: bytes
) -> RawHttpCall | None:
    if method_name in HTTP_VERBS:
        method: str | None = method_name.upper()
        url = argument(call, 0, "url")
    elif method_name == "request":
        method_text = plain_string(argument(call, 0, "method"), source)
        method = method_text.upper() if method_text else None
        url = argument(call, 1, "url")
    else:
        return None
    url_text, url_kind = classify_url(url, source)
    return RawHttpCall(scope, client, url_text, url_kind, method, line(call))


def classify_url(node: TSNode | None, source: bytes) -> tuple[str, str]:
    """`(url_text, url_kind)` for a URL argument."""
    if node is None:
        return "", "dynamic"
    value = string_value(node, source)
    if value is not None:
        return value.content, "template" if value.is_fstring else "literal"
    if node.type == "call":
        template = _format_template(node, source)
        if template is not None:
            return template, "template"
    return one_line(node, source), "dynamic"


def _format_template(call: TSNode, source: bytes) -> str | None:
    """The string in `"/users/{}".format(user_id)`, else None."""
    function = call.child_by_field_name("function")
    if function is None or function.type != "attribute":
        return None
    attribute = function.child_by_field_name("attribute")
    if attribute is None or text(attribute, source) != "format":
        return None
    return plain_string(function.child_by_field_name("object"), source)


def _client_for(name: str, scope: str, clients: dict[tuple[str, str], str]) -> str | None:
    """A client variable in the caller's own function first, then at module level."""
    return clients.get((scope, name)) or clients.get(("", name))


def _client_variables(root: TSNode, source: bytes, scopes: Scopes) -> dict[tuple[str, str], str]:
    """`(scope, variable) -> client` for `x = httpx.Client()` and `with ... as x`.

    Module-level variables are stored under scope `""` so any function can find them.
    """
    clients: dict[tuple[str, str], str] = {}
    for node in walk(root):
        if node.type == "assignment":
            name, value = node.child_by_field_name("left"), node.child_by_field_name("right")
        elif node.type == "as_pattern":
            name, value = node.child_by_field_name("alias"), node.named_children[0]
            name = name.named_children[0] if name is not None and name.named_child_count else name
        else:
            continue
        if name is None or value is None or name.type != "identifier" or value.type != "call":
            continue
        parts = callee_parts(value, source)
        client = _CLIENT_FACTORIES.get(parts[0]) if parts else None
        if client is None:
            continue
        scope = scopes.caller_key(node)
        clients[("" if scope == scopes.module_key else scope, text(name, source))] = client
    return clients
