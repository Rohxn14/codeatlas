
from ts_samples import parse_sample

from codeatlas.indexer.languages.typescript.routes import normalise_path
from codeatlas.models import RawHttpCall, RawRoute


def test_express_routes() -> None:
    s = "web/server.js::"
    assert parse_sample("server.js").routes == (
        RawRoute(f"{s}listUsers", "GET", "/api/users", "express", "app", 9),
        RawRoute(s, "POST", "/api/users/{id}", "express", "app", 10),  # inline handler
        RawRoute(s, "DELETE", "/items/{itemId}", "express", "router", 11),  # imported handler
        RawRoute(f"{s}listUsers", "PUT", "/orders/{id}", "express", "router", 12),
        RawRoute(s, "GET", "/orders/{id}", "express", "router", 12),  # showOrder: not here
        RawRoute(s, "ANY", "/health", "express", "app", 13),
    )  # app.get("title") reads a setting; app.use mounts a router


def test_path_normalisation() -> None:
    assert normalise_path("/a/:id/b/:slug?") == "/a/{id}/b/{slug}"
    assert normalise_path(r"/n/:num(\d+)") == "/n/{num}"
    assert normalise_path("/plain") == "/plain"


def test_fetch_and_axios() -> None:
    c = "web/client.ts::"
    assert parse_sample("client.ts").http_calls == (
        RawHttpCall(f"{c}loadUser", "fetch", "/api/users/${id}", "template", "GET", 6),
        RawHttpCall(f"{c}saveUser", "fetch", "/api/users", "literal", "POST", 11),
        RawHttpCall(f"{c}search", "fetch", "url", "dynamic", None, 15),
        RawHttpCall(f"{c}listOrders", "axios", "/api/orders", "literal", "GET", 18),
        RawHttpCall(f"{c}createOrder", "axios", "/api/orders", "literal", "POST", 21),
        RawHttpCall(f"{c}getProfile", "axios", "/api/profiles/${id}", "template", "GET", 25),
        RawHttpCall(
            f"{c}deleteProfile", "axios", '"/api" + "/profiles/" + id', "dynamic", "DELETE", 29
        ),
    )


def test_axios_get_with_a_path_is_not_a_route() -> None:
    from codeatlas.indexer.languages.typescript.adapter import JavaScriptAdapter

    source = b'const api = axios.create({});\napi.get("/x", cfg);\naxios.post("/y", body);\n'
    result = JavaScriptAdapter().parse("a.js", source, "s@1")
    assert result.routes == ()
    assert [(h.url_text, h.method) for h in result.http_calls] == [("/x", "GET"), ("/y", "POST")]


def _js(source: bytes):
    from codeatlas.indexer.languages.typescript.adapter import JavaScriptAdapter

    return JavaScriptAdapter().parse("a.js", source, "s@0")


def test_plain_value_arguments_are_not_route_handlers() -> None:
    result = _js(b"""import { api } from "./client";
api.get("/users", { params: { page: 1 } });
cache.get("/key", 1);
cache.get("key", fallback);
app.get("/ok", listUsers);
""")
    assert [(r.method, r.path_pattern) for r in result.routes] == [("GET", "/ok")]


def test_base_url_joins_with_exactly_one_slash() -> None:
    from codeatlas.indexer.languages.typescript.http import join_url

    assert join_url("https://x.io/api/", "/users") == "https://x.io/api/users"
    assert join_url("/api", "users") == "/api/users"
    assert join_url("/api", "/users") == "/api/users"
    assert join_url("/api", "?q=1") == "/api?q=1"
    assert join_url("/api", "https://other.io/x") == "https://other.io/x"
    result = _js(b"""import axios from "axios";
const http = axios.create({ baseURL: "https://x.io/api/" });
function load() { return http.get("/users"); }
""")
    assert [c.url_text for c in result.http_calls] == ["https://x.io/api/users"]
