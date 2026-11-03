"""The polyglot fixture through `build_graph` with the HTTP linker registered."""

from __future__ import annotations

from pathlib import Path

from codeatlas.indexer.pipeline import build_graph
from codeatlas.store import GraphStore

FIXTURE = Path(__file__).resolve().parents[3] / "eval" / "fixtures" / "polyglot_app"


def test_fixture_routes_handles_and_reachable_calls(tmp_path: Path) -> None:
    store = GraphStore(tmp_path / "t.db")
    try:
        built = build_graph(str(FIXTURE), store)
        export = store.export_json(built.snapshot_id)
    finally:
        store.close()
    routes = {n["key"] for n in export["nodes"] if n["kind"] == "route"}
    assert routes == {
        "backend/routes.py::route:GET /api/users",
        "backend/routes.py::route:GET /api/users/{id}",
        "backend/routes.py::route:POST /api/users",
    }
    handles = [e for e in export["edges"] if e["kind"] == "handles"]
    assert len(handles) == 3
    http = {(e["src_key"], e["dst_key"]) for e in export["edges"] if e["kind"] == "calls_http"}
    client, tests, routes_py = (
        "frontend/src/api/client.ts::",
        "backend/tests/test_routes.py::test_routes_create_list_and_get",
        "backend/routes.py::route:",
    )
    assert http == {
        (f"{client}fetchUsers", f"{routes_py}GET /api/users"),
        (f"{client}fetchUser", f"{routes_py}GET /api/users/{{id}}"),
        (f"{client}createUser", f"{routes_py}POST /api/users"),  # axios instance from http.ts
        (tests, f"{routes_py}POST /api/users"),  # TestClient
        (tests, f"{routes_py}GET /api/users/{{id}}"),
        (tests, f"{routes_py}GET /api/users"),
    }


def test_linker_problems_reach_the_build_report(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "web").mkdir(parents=True)
    (repo / "web" / "server.js").write_text(
        'const app = express();\napp.get("/ping", (req, res) => res.send("ok"));\n'
    )
    (repo / "web" / "client.js").write_text(
        'export function f() { return fetch("/nowhere"); }\n'
    )
    store = GraphStore(tmp_path / "t.db")
    try:
        problems = build_graph(str(repo), store).problems
    finally:
        store.close()
    assert "linker http: route GET /ping: inline handler, no HANDLES edge" in problems
    assert "linker http: unmatched http calls: no_route=1" in problems
