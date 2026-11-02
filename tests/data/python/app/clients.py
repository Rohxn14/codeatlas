import httpx
import requests

BASE = "http://api.local"
session = requests.Session()


def fetch_user(user_id):
    return requests.get(f"{BASE}/api/users/{user_id}")


def create_user(payload):
    return requests.post("/api/users", json=payload)


def raw(url, verb):
    requests.request("DELETE", url)
    return requests.request(verb, url="/api/raw")


def with_session():
    return session.get("/orders/{}".format(7))


async def with_client(path):
    async with httpx.AsyncClient(base_url=BASE) as client:
        await client.put(BASE + path)
    other = httpx.Client()
    other.patch(url="/api/users/1")
    return httpx.delete("/api/users/2")


def not_a_client(cache):
    return cache.get("/api/users")
