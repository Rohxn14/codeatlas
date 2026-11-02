"""Shared fixture data and the scripted fake LLM provider for the agent tests."""

from __future__ import annotations

from collections.abc import Sequence

from codeatlas.llm import LLMClient, LLMResponse, Message, ToolCall, ToolSpec
from codeatlas.models import (
    Edge,
    EdgeKind,
    FileRecord,
    Node,
    NodeKind,
    Resolution,
    Snapshot,
    Span,
    Tier,
    make_node_id,
    make_snapshot_id,
)
from codeatlas.store import GraphStore

SHA = "3f2a9c1e5b7d" + "0" * 28
SNAP = make_snapshot_id("demo", SHA)  # demo@3f2a9c1e5b7d

FILES = {
    "app/repo.py": (
        "class Repo:\n"
        "    def save(self, user):\n"
        "        '''Store a user.'''\n"
        "        return user\n"
    ),
    "app/service.py": (
        "from app.repo import Repo\n"
        "\n"
        "def create(user):\n"
        "    return Repo().save(user)\n"
        "\n"
        "def rename(user):\n"
        "    return create(user)\n"
    ),
    "tests/test_service.py": (
        "from app.service import create\n"
        "\n"
        "def test_create():\n"
        "    assert create(1)\n"
    ),
}


def _node(key: str, kind: NodeKind, path: str, start: int, end: int, **kw: object) -> Node:
    qualname = key.split("::", 1)[1]
    return Node(make_node_id(SNAP, key), key, SNAP, kind, "python", qualname.rsplit(".", 1)[-1],
                qualname, path, Span(start, end), **kw)  # type: ignore[arg-type]


def _edge(src: str, dst: str, kind: EdgeKind, conf: float, res: Resolution, line: int) -> Edge:
    return Edge(make_node_id(SNAP, src), make_node_id(SNAP, dst), kind, conf, res, line)


def populate(store: GraphStore, source: str, snapshot_id: str = SNAP) -> None:
    store.create_snapshot(Snapshot(snapshot_id, "demo", SHA, "2026-11-01T00:00:00Z", "0.1.0",
                                   source))
    store.write_files(snapshot_id, [FileRecord(p, "python", Tier.DEEP, "x", len(t))
                                    for p, t in FILES.items()])
    store.write_nodes([
        _node("app/repo.py::", NodeKind.MODULE, "app/repo.py", 1, 4),
        _node("app/repo.py::Repo", NodeKind.CLASS, "app/repo.py", 1, 4),
        _node("app/repo.py::Repo.save", NodeKind.FUNCTION, "app/repo.py", 2, 4,
              signature="def save(self, user)", docstring="Store a user.",
              owner_key="app/repo.py::Repo"),
        _node("app/service.py::", NodeKind.MODULE, "app/service.py", 1, 7),
        _node("app/service.py::create", NodeKind.FUNCTION, "app/service.py", 3, 4,
              signature="def create(user)"),
        _node("app/service.py::rename", NodeKind.FUNCTION, "app/service.py", 6, 7,
              signature="def rename(user)"),
        _node("tests/test_service.py::", NodeKind.MODULE, "tests/test_service.py", 1, 4),
        _node("tests/test_service.py::test_create", NodeKind.TEST, "tests/test_service.py", 3, 4),
    ])
    store.write_edges(snapshot_id, [
        _edge("app/service.py::create", "app/repo.py::Repo.save", EdgeKind.CALLS, 0.5,
              Resolution.IMPORT_SCOPED, 4),
        _edge("app/service.py::rename", "app/service.py::create", EdgeKind.CALLS, 1.0,
              Resolution.DIRECT, 7),
        _edge("app/service.py::", "app/repo.py::", EdgeKind.IMPORTS, 1.0,
              Resolution.STRUCTURAL, 1),
        _edge("tests/test_service.py::", "app/service.py::", EdgeKind.IMPORTS, 1.0,
              Resolution.STRUCTURAL, 1),
        _edge("tests/test_service.py::test_create", "app/service.py::create", EdgeKind.TESTS,
              0.8, Resolution.CONVENTION, 3),
        _edge("app/service.py::", "app/repo.py::", EdgeKind.CO_CHANGES, 0.6,
              Resolution.HISTORY, None),
        _edge("app/repo.py::", "app/service.py::", EdgeKind.CO_CHANGES, 0.6,
              Resolution.HISTORY, None),
    ])


class ScriptedProvider:
    """Answers each chat call with the next scripted response; records every request."""

    name = "scripted"
    model = "scripted-1"

    def __init__(self, replies: Sequence[LLMResponse]) -> None:
        self.replies = list(replies)
        self.requests: list[list[Message]] = []

    def chat(self, messages: Sequence[Message], tools: Sequence[ToolSpec] | None,
             temperature: float, max_tokens: int | None) -> LLMResponse:
        self.requests.append(list(messages))
        return self.replies.pop(0)

    def list_models(self) -> list:
        return []


def reply(text: str = "", calls: Sequence[ToolCall] = (), tokens: tuple[int, int] = (10, 5)):
    return LLMResponse(text, tuple(calls), "scripted", "scripted-1", tokens[0], tokens[1])


def make_client(*replies: LLMResponse) -> tuple[LLMClient, ScriptedProvider]:
    provider = ScriptedProvider(replies)
    return LLMClient([provider], cache_mode="off"), provider
