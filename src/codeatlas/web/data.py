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
    by_key: dict[str, Node] = field(default_factory=dict)
    out_edges: dict[str, list[Edge]] = field(default_factory=dict)
    in_edges: dict[str, list[Edge]] = field(default_factory=dict)
    overview: dict[str, Any] | None = None


def load_snapshot(
    store: GraphStore, snapshot: Snapshot, report: dict[str, Any] | None = None
) -> Loaded:
    nodes = {node.id: node for node in store.nodes(snapshot.id)}
    edges = store.edges(snapshot.id)
    out_edges: dict[str, list[Edge]] = {}
    in_edges: dict[str, list[Edge]] = {}
    for edge in edges:
        out_edges.setdefault(edge.src_id, []).append(edge)
        in_edges.setdefault(edge.dst_id, []).append(edge)
    return Loaded(
        snapshot=snapshot,
        nodes=nodes,
        edges=edges,
        files=store.files(snapshot.id),
        calls=store.raw_calls(snapshot.id),
        report=report,
        links=file_links(nodes, edges),
        by_key={node.key: node for node in nodes.values()},
        out_edges=out_edges,
        in_edges=in_edges,
    )
