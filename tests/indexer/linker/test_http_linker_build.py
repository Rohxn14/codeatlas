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
    assert (
        "frontend/src/api/client.ts::fetchUsers", "backend/routes.py::route:GET /api/users"
    ) in http
    assert (
        "frontend/src/api/client.ts::fetchUser", "backend/routes.py::route:GET /api/users/{id}"
    ) in http
