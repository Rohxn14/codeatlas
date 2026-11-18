"""Mocked HTTP for both providers: canned responses, and a record of every request made."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent.parent / "data" / "llm"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Script:
    """Replies to chat requests from a queue of (status, body[, headers]); lists models too."""

    def __init__(self, replies: list[tuple], models: dict | None = None) -> None:
        self.replies = list(replies)
        self.models = models
        self.chat_requests: list[dict] = []
        self.model_requests = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/models"):
            self.model_requests += 1
            if self.models is None:
                return httpx.Response(500, json={"error": {"message": "no list"}})
            return httpx.Response(200, json=self.models)
        self.chat_requests.append(
            {"path": request.url.path, "body": json.loads(request.content or b"{}")}
        )
        status, body, *headers = self.replies.pop(0)  # an optional third item: headers
        return httpx.Response(status, json=body, headers=headers[0] if headers else None)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture
def script() -> Callable[..., Script]:
    return Script
