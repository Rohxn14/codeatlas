from fastapi.testclient import TestClient

from backend.app import create_app


def test_routes_create_list_and_get():
    client = TestClient(create_app())
    created = client.post("/api/users", json={"name": "ada"})
    assert created.status_code == 200
    user_id = created.json()["id"]
    assert client.get(f"/api/users/{user_id}").json()["name"] == "ada"
    assert any(u["name"] == "ada" for u in client.get("/api/users").json())
    assert client.get("/api/users/999").status_code == 404
