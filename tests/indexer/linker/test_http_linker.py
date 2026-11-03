"""HTTP linker tests on hand-made parse results: no parsing, no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.indexer.linker import HttpLinker
from codeatlas.indexer.linker.urls import normalise_client_url
from codeatlas.models import (
    EdgeKind,
    NodeKind,
    ParseResult,
    RawHttpCall,
    RawRoute,
    Resolution,
    Tier,
)

SNAP = "repo@abc"


def server(*routes: RawRoute, path: str = "backend/routes.py") -> ParseResult:
    return ParseResult(path, "python", Tier.DEEP, nodes=(), routes=routes)


def client(*calls: RawHttpCall, path: str = "web/api.ts") -> ParseResult:
    return ParseResult(path, "typescript", Tier.DEEP, nodes=(), http_calls=calls)


def route(method: str, pattern: str, handler: str = "backend/routes.py::h", **kw) -> RawRoute:
    return RawRoute(handler, method, pattern, kw.pop("framework", "fastapi"), line=3, **kw)


def call(url: str, kind: str = "literal", method: str | None = "GET", client: str = "fetch"):
    return RawHttpCall("web/api.ts::f", client, url, kind, method, 5)


def run(*results: ParseResult):
    linker = HttpLinker()
    nodes, edges = linker.link(list(results), None, SNAP)  # type: ignore[arg-type]
    return linker, nodes, edges


def calls_edges(edges):
    return [e for e in edges if e.kind is EdgeKind.CALLS_HTTP]


def test_literal_fetch_is_exact() -> None:
    _, nodes, edges = run(server(route("GET", "/api/users")), client(call("/api/users")))
    (edge,) = calls_edges(edges)
    assert (edge.resolution, edge.confidence) == (Resolution.ROUTE_EXACT, 0.9)
    assert edge.src_id == f"{SNAP}/web/api.ts::f"
    assert edge.dst_id == f"{SNAP}/backend/routes.py::route:GET /api/users"
    (node,) = nodes
    assert node.kind is NodeKind.ROUTE
    assert node.attrs == {
        "http_method": "GET", "path_pattern": "/api/users", "framework": "fastapi"
    }


def test_route_node_has_handles_edge() -> None:
    _, _, edges = run(server(route("GET", "/api/users", "backend/routes.py::list_users")))
    (edge,) = edges
    assert edge.kind is EdgeKind.HANDLES
    assert edge.dst_id == f"{SNAP}/backend/routes.py::list_users"
    assert (edge.resolution, edge.confidence) == (Resolution.STRUCTURAL, 1.0)


def test_template_fetch_is_pattern() -> None:
    _, _, edges = run(
        server(route("GET", "/api/users/{id}")), client(call("/api/users/${id}", "template"))
    )
    (edge,) = calls_edges(edges)
    assert (edge.resolution, edge.confidence) == (Resolution.ROUTE_PATTERN, 0.7)


def test_literal_against_param_is_pattern() -> None:
    _, _, edges = run(server(route("GET", "/users/{id}")), client(call("/users/999")))
    assert calls_edges(edges)[0].resolution is Resolution.ROUTE_PATTERN


def _ts(path: str, source: bytes) -> ParseResult:
    from codeatlas.indexer.languages.typescript.adapter import TypeScriptAdapter

    return TypeScriptAdapter().parse(path, source, SNAP)


FIXTURE_API = Path(__file__).resolve().parents[3] / "eval/fixtures/polyglot_app/frontend/src/api"


def test_axios_instance_imported_from_another_file_gets_its_base_url() -> None:
    http = _ts("frontend/src/api/http.ts", (FIXTURE_API / "http.ts").read_bytes())
    calls = _ts("frontend/src/api/client.ts", (FIXTURE_API / "client.ts").read_bytes())
    linker, _, edges = run(server(route("POST", "/api/users")), http, calls)
    got = [e for e in calls_edges(edges) if e.src_id.endswith("::createUser")]
    (edge,) = got
    assert edge.dst_id.endswith("route:POST /api/users")
    assert edge.resolution is Resolution.ROUTE_EXACT
    assert edge.attrs == {"url": "/api/users", "client": "axios"}


@pytest.mark.parametrize(
    ("export", "binding"),
    [
        (b'export default axios.create({ baseURL: "/api" });', b"api"),
        (b'const a = axios.create({ baseURL: "/api" });\nexport default a;', b"api"),
        (b'const a = axios.create({ baseURL: "/api" });\nexport { a as api };', b"{ api }"),
    ],
)
def test_other_export_forms(export: bytes, binding: bytes) -> None:
    lib = _ts("web/lib/index.ts", b'import axios from "axios";\n' + export)
    use = _ts("web/use.ts", b"import " + binding + b' from "./lib";\n'
              b'function f() { return api.get(`/users/${1}`); }\n')
    _, _, edges = run(server(route("GET", "/api/users/{id}")), lib, use)
    assert [e.dst_id.rpartition("route:")[2] for e in calls_edges(edges)] == [
        "GET /api/users/{id}"
    ]


def test_imported_name_that_is_not_an_instance_is_unknown_client() -> None:
    lib = _ts("web/store.ts", b"export const cache = new Map();\n")
    use = _ts("web/use.ts", (
        b'import { cache } from "./store";\n'
        b'function f() { cache.get("/a"); }\n'
    ))
    linker, _, edges = run(server(route("GET", "/a")), lib, use)
    assert calls_edges(edges) == []
    assert linker.unmatched == {"unknown_client": 1}
    assert linker.problems == ["unmatched http calls: unknown_client=1"]


def test_aliased_import_found_by_unique_exported_name() -> None:
    lib = _ts("src/api/http.ts", b'export const http = axios.create({ baseURL: "/api" });\n')
    use = _ts("src/views/a.ts", (
        b'import { http } from "@/api/http";\n'
        b'function f() { http.get("/x"); }\n'
    ))
    _, _, edges = run(server(route("GET", "/api/x")), lib, use)
    assert len(calls_edges(edges)) == 1


def test_express_route_on_imported_router_is_not_a_client_call() -> None:
    use = _ts("srv/a.ts", b'import { router } from "./r";\nrouter.get("/x", listThings);\n')
    assert use.http_calls == ()


def test_dynamic_concatenation() -> None:
    _, _, edges = run(
        server(route("GET", "/api/users/{id}")),
        client(call('BASE + "/api/users/" + id', "dynamic")),
    )
    assert calls_edges(edges)[0].resolution is Resolution.ROUTE_PATTERN


def test_requests_and_testclient_with_localhost_host() -> None:
    py = ParseResult(
        "tests/t.py", "python", Tier.DEEP, nodes=(),
        http_calls=(
            RawHttpCall(
                "tests/t.py::t", "requests", "http://localhost:8000/api/users/",
                "literal", "GET", 2,
            ),
            RawHttpCall("tests/t.py::t", "testclient", "/api/users", "literal", "POST", 3),
        ),
    )
    _, _, edges = run(server(route("GET", "/api/users"), route("POST", "/api/users")), py)
    assert {e.dst_id.rpartition("route:")[2] for e in calls_edges(edges)} == {
        "GET /api/users", "POST /api/users"
    }


def test_flask_blueprint_and_express_params() -> None:
    flask = server(route("GET", "/v1/items/{item_id}", framework="flask"), path="app/bp.py")
    express = server(route("GET", "/items/{id}", framework="express"), path="srv/app.js")
    _, _, edges = run(flask, express, client(call("/v1/items/${x}", "template")))
    (edge,) = calls_edges(edges)
    assert edge.dst_id.endswith("app/bp.py::route:GET /v1/items/{item_id}")


def test_inline_handler_makes_route_without_handles_and_counts_problem() -> None:
    linker, nodes, edges = run(
        server(route("GET", "/ping", "srv/app.js::", framework="express"), path="srv/app.js")
    )
    assert len(nodes) == 1 and edges == []
    assert len(linker.problems) == 1


def test_unknown_method_matches_any_at_pattern_level() -> None:
    _, _, edges = run(
        server(route("GET", "/a"), route("DELETE", "/a")), client(call("/a", method=None))
    )
    got = calls_edges(edges)
    assert len(got) == 2
    assert all(e.resolution is Resolution.ROUTE_PATTERN for e in got)


def test_route_any_matches_every_method() -> None:
    _, _, edges = run(server(route("ANY", "/a")), client(call("/a", method="PUT")))
    assert calls_edges(edges)[0].resolution is Resolution.ROUTE_PATTERN


def test_method_mismatch_and_no_route_are_unmatched() -> None:
    linker, _, edges = run(
        server(route("GET", "/a")), client(call("/a", method="POST"), call("/zzz"))
    )
    assert calls_edges(edges) == []
    assert linker.unmatched == {"no_route": 2}
    assert linker.problems == ["unmatched http calls: no_route=2"]


def test_exact_method_route_beats_any() -> None:
    _, _, edges = run(server(route("GET", "/x"), route("ANY", "/x")), client(call("/x")))
    (edge,) = calls_edges(edges)
    assert edge.dst_id.endswith("route:GET /x")
    assert (edge.resolution, edge.confidence) == (Resolution.ROUTE_EXACT, 0.9)


def test_segment_mixing_parameter_and_text() -> None:
    files = server(route("GET", "/files/{name}.json"))
    _, _, edges = run(files, client(call("/files/report.json")))
    assert calls_edges(edges)[0].resolution is Resolution.ROUTE_PATTERN
    linker, _, _ = run(files, client(call("/files/report.xml"), call("/files/${n}", "template")))
    assert linker.unmatched == {"no_route": 2}


def test_two_routes_one_call_prefers_specific_then_splits() -> None:
    routes = server(route("GET", "/users/{id}"), route("GET", "/users/me"))
    _, _, edges = run(routes, client(call("/users/me")))
    (edge,) = calls_edges(edges)
    assert edge.dst_id.endswith("GET /users/me") and edge.resolution is Resolution.ROUTE_EXACT

    tied = server(route("GET", "/users/{id}"), route("GET", "/users/{name}"))
    _, _, edges = run(tied, client(call("/users/${x}", "template")))
    got = calls_edges(edges)
    assert len(got) == 2
    assert all(e.confidence == pytest.approx(0.35) for e in got)


def test_full_host_is_unmatched_external() -> None:
    linker, _, edges = run(
        server(route("GET", "/users")), client(call("https://api.github.com/users"))
    )
    assert calls_edges(edges) == []
    assert linker.unmatched == {"external_host": 1}


def test_dynamic_url_is_unmatched() -> None:
    linker, _, _ = run(server(route("GET", "/a")), client(call("buildUrl(x)", "dynamic")))
    assert linker.unmatched == {"dynamic": 1}


@pytest.mark.parametrize(
    ("text", "kind", "segments"),
    [
        ("http://localhost:8000/api/users?x=1#top", "literal", ("api", "users")),
        ("${API}/users", "template", ("users",)),
        ("{BASE}/users/{user_id}", "template", ("users", "{}")),
        ("/a//b/", "literal", ("a", "b")),
        ('"/users/" + id', "dynamic", ("users", "{}")),
        ("http://${API_HOST}:8000/api/users", "template", ("api", "users")),
        ("http://{host}/api/users", "template", ("api", "users")),
        ("http://[::1]:8000/x", "literal", ("x",)),
        ("HTTP://LOCALHOST/x", "literal", ("x",)),
        ("/api/users/${q ? 'a' : 'b'}", "template", ("api", "users", "{}")),
        ("/a/${x}?q=${y#z}", "template", ("a", "{}")),
        ("'/api/users/' + ids[0]", "dynamic", ("api", "users", "{}")),
        ("'/api/' + row['kind'] + '/' + user.id", "dynamic", ("api", "{}", "{}")),
        ("//localhost/api/users", "literal", ("api", "users")),
    ],
)
def test_normalise(text: str, kind: str, segments: tuple[str, ...]) -> None:
    assert normalise_client_url(text, kind).segments == segments


def test_protocol_relative_external_host() -> None:
    assert normalise_client_url("//cdn.example.com/x", "literal").reason == "external_host"


def test_paths_are_case_sensitive() -> None:
    linker, _, _ = run(server(route("GET", "/Users")), client(call("/users")))
    assert linker.unmatched == {"no_route": 1}
