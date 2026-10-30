from pathlib import Path

import pytest

from codeatlas.indexer.languages.python.adapter import PythonAdapter
from codeatlas.indexer.languages.python.routes import normalise_path
from codeatlas.models import ParseResult, RawHttpCall, RawRoute

SNAPSHOT = "demo@0123456789ab"
DATA = Path(__file__).parents[2] / "data" / "python"


def parse(rel: str) -> ParseResult:
    return PythonAdapter().parse(rel, (DATA / rel).read_bytes(), SNAPSHOT)


def test_fastapi_routes_with_a_router_prefix() -> None:
    k = "app/fastapi_routes.py::"
    assert parse("app/fastapi_routes.py").routes == (
        RawRoute(f"{k}health", "GET", "/health", "fastapi", "app", 7),
        RawRoute(f"{k}get_user", "GET", "/api/users/{user_id}", "fastapi", "router", 12),
        RawRoute(f"{k}create_user", "POST", "/api/users", "fastapi", "router", 17),
        RawRoute(f"{k}sync_user", "PUT", "/api/users/{user_id}/sync", "fastapi", "router", 22),
        RawRoute(f"{k}sync_user", "PATCH", "/api/users/{user_id}/sync", "fastapi", "router", 22),
        RawRoute(f"{k}get_item", "GET", "/items/{item_id}", "fastapi", "app", 27),
    )


def test_flask_routes_with_a_blueprint_prefix() -> None:
    k = "app/flask_routes.py::"
    assert parse("app/flask_routes.py").routes == (
        RawRoute(f"{k}index", "GET", "/", "flask", "app", 7),
        RawRoute(f"{k}login", "GET", "/login", "flask", "app", 12),
        RawRoute(f"{k}login", "POST", "/login", "flask", "app", 12),
        RawRoute(f"{k}get_order", "GET", "/orders/{order_id}", "flask", "bp", 17),
        # methods=METHODS is a variable, so the method is unknown.
        RawRoute(f"{k}order_item", "ANY", "/orders/{order_id}/items/{item}", "flask", "bp", 22),
    )


def test_router_imported_from_elsewhere_defaults_by_evidence() -> None:
    source = (
        b"from .app import app, bp\n\n"
        b"@app.get('/a')\ndef a(): pass\n\n"
        b"@bp.route('/b')\ndef b(): pass\n\n"
        b"@app.get(make_path())\ndef c(): pass\n"
    )
    routes = PythonAdapter().parse("views.py", source, SNAPSHOT).routes
    assert [(r.handler_key, r.framework, r.path_pattern) for r in routes] == [
        ("views.py::a", "fastapi", "/a"),
        ("views.py::b", "flask", "/b"),
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/users/<int:id>", "/users/{id}"),
        ("/users/<id>", "/users/{id}"),
        ("/users/{id}", "/users/{id}"),
        ("/files/{path:path}", "/files/{path}"),
        ("/a/<string:x>/b/<y>", "/a/{x}/b/{y}"),
    ],
)
def test_normalise_path(raw: str, expected: str) -> None:
    assert normalise_path(raw) == expected


def test_http_calls_with_literal_template_and_dynamic_urls() -> None:
    k = "app/clients.py::"
    assert parse("app/clients.py").http_calls == (
        RawHttpCall(f"{k}fetch_user", "requests", "{BASE}/api/users/{user_id}", "template",
                    "GET", 9),
        RawHttpCall(f"{k}create_user", "requests", "/api/users", "literal", "POST", 13),
        RawHttpCall(f"{k}raw", "requests", "url", "dynamic", "DELETE", 17),
        RawHttpCall(f"{k}raw", "requests", "/api/raw", "literal", None, 18),
        # `session` is a module-level requests.Session().
        RawHttpCall(f"{k}with_session", "requests", "/orders/{}", "template", "GET", 22),
        # `async with httpx.AsyncClient() as client` and `other = httpx.Client()`.
        RawHttpCall(f"{k}with_client", "httpx", "BASE + path", "dynamic", "PUT", 27),
        RawHttpCall(f"{k}with_client", "httpx", "/api/users/1", "literal", "PATCH", 29),
        RawHttpCall(f"{k}with_client", "httpx", "/api/users/2", "literal", "DELETE", 30),
    )


def test_client_variables_are_scoped_to_their_function() -> None:
    source = (
        b"import httpx\n\n"
        b"def a():\n    client = httpx.Client()\n    client.get('/a')\n\n"
        b"def b(client):\n    client.get('/b')\n"
    )
    calls = PythonAdapter().parse("c.py", source, SNAPSHOT).http_calls
    assert [(c.caller_key, c.url_text) for c in calls] == [("c.py::a", "/a")]
