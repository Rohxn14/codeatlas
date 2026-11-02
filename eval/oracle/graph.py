"""Read graph files in the export shape of docs/contract.md section 8.

Three kinds of file share this shape: a CodeAtlas export (the prediction), a
hand-labelled `expected_graph.json` and a SCIP oracle file (the truth). Truth files may
add an `"unresolvable"` list: call sites no static indexer can resolve, which the
scorer keeps out of precision. Everything is compared by node key, so the reader keeps
keys and drops snapshot-specific ids.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
}


@dataclass(frozen=True, slots=True)
class GraphNode:
    key: str
    kind: str
    language: str
    path: str
    start_line: int = 0
    end_line: int = 0


@dataclass(frozen=True, slots=True)
class GraphEdge:
    src_key: str
    dst_key: str
    kind: str
    confidence: float = 1.0
    resolution: str = ""
    line: int | None = None

    @property
    def triple(self) -> tuple[str, str, str]:
        """What makes two edges the same edge: the line is for debugging only."""
        return (self.src_key, self.dst_key, self.kind)


@dataclass(frozen=True, slots=True)
class Unresolvable:
    src_key: str
    line: int
    callee_text: str = ""
    reason: str = ""


@dataclass(slots=True)
class Graph:
    snapshot: dict[str, object]
    nodes: dict[str, GraphNode]
    edges: list[GraphEdge]
    unresolvable: list[Unresolvable] = field(default_factory=list)


def path_of_key(key: str) -> str:
    """The file part of a node key: `backend/users.py::User.save` -> `backend/users.py`."""
    return key.split("::", 1)[0]


def language_of_path(path: str) -> str:
    return LANGUAGE_BY_SUFFIX.get(PurePosixPath(path).suffix.lower(), "text")


def load_graph(path: Path) -> Graph:
    return parse_graph(json.loads(path.read_text(encoding="utf-8")))


def parse_graph(data: dict[str, object]) -> Graph:
    nodes = {n.key: n for n in map(_node, _list(data, "nodes"))}
    edges = [_edge(e) for e in _list(data, "edges")]
    unresolvable = [
        Unresolvable(
            str(u["src_key"]), int(u["line"]), str(u.get("callee_text", "")),
            str(u.get("reason", "")),
        )
        for u in _list(data, "unresolvable")
    ]
    snapshot = data.get("snapshot")
    return Graph(snapshot if isinstance(snapshot, dict) else {}, nodes, edges, unresolvable)


def _list(data: dict[str, object], name: str) -> list[dict[str, object]]:
    value = data.get(name, [])
    if not isinstance(value, list):
        raise ValueError(f"'{name}' must be a list")
    return value


def _node(raw: dict[str, object]) -> GraphNode:
    key = str(raw["key"])
    path = str(raw.get("path") or path_of_key(key))
    span = raw.get("span")
    span = span if isinstance(span, dict) else {}
    return GraphNode(
        key=key,
        kind=str(raw.get("kind", "")),
        language=str(raw.get("language") or language_of_path(path)),
        path=path,
        start_line=int(span.get("start_line", 0)),
        end_line=int(span.get("end_line", 0)),
    )


def _edge(raw: dict[str, object]) -> GraphEdge:
    line = raw.get("line")
    return GraphEdge(
        src_key=str(raw["src_key"]),
        dst_key=str(raw["dst_key"]),
        kind=str(raw["kind"]),
        confidence=float(raw.get("confidence", 1.0)),
        resolution=str(raw.get("resolution", "")),
        line=int(line) if line is not None else None,
    )
