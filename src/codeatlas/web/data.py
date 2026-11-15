"""One snapshot read from the store once and kept in memory for the pages to share.

A snapshot never changes after it is written, so reading it on every request would only
repeat work. The cost is memory: every node and edge of each opened snapshot stays
loaded while the server runs (product plan B4 is the fix when that becomes too much).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from codeatlas.models import Edge, FileRecord, Node, RawCall, Snapshot
from codeatlas.store import GraphStore
from codeatlas.web.diagram import Link, file_links


@dataclass(slots=True)
class Loaded:
    """Everything the pages read about one snapshot."""

    snapshot: Snapshot
    nodes: dict[str, Node]
    edges: list[Edge]
    files: list[FileRecord]
    calls: list[tuple[RawCall, bool]]
    report: dict[str, Any] | None
    links: list[Link] = field(default_factory=list)
    overview: dict[str, Any] | None = None


def load_snapshot(
    store: GraphStore, snapshot: Snapshot, report: dict[str, Any] | None = None
) -> Loaded:
    nodes = {node.id: node for node in store.nodes(snapshot.id)}
    edges = store.edges(snapshot.id)
    return Loaded(
        snapshot=snapshot,
        nodes=nodes,
        edges=edges,
        files=store.files(snapshot.id),
        calls=store.raw_calls(snapshot.id),
        report=report,
        links=file_links(nodes, edges),
    )
