"""The facts on the file, symbol and search pages, taken from one loaded snapshot.

Each function returns plain values for a template. None of them reads the store or the
disk, so they can be tested with a handful of nodes and edges.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from codeatlas.models import Edge, EdgeKind, Node, NodeKind
from codeatlas.web.confidence import LEVELS, level
from codeatlas.web.data import Loaded

# Kinds listed on a file's outline and found by search.
SYMBOL_KINDS = (NodeKind.CLASS, NodeKind.INTERFACE, NodeKind.FUNCTION, NodeKind.TEST,
                NodeKind.ROUTE)
# Relations shown on a symbol page. Containment is the outline; co-change is per file.
RELATION_KINDS = (EdgeKind.CALLS, EdgeKind.CALLS_HTTP, EdgeKind.HANDLES, EdgeKind.INHERITS,
                  EdgeKind.IMPORTS, EdgeKind.TESTS)
MAX_ROWS = 200
MAX_HITS = 50


def file_page(loaded: Loaded, path: str) -> dict[str, Any] | None:
    """What is known about one file, or None when the snapshot has no such file."""
    record = next((f for f in loaded.files if f.path == path), None)
    if record is None:
        return None
    inside = [n for n in loaded.nodes.values() if n.path == path]
    module = next((n for n in inside if n.kind is NodeKind.MODULE), None)
    symbols = sorted((n for n in inside if n.kind in SYMBOL_KINDS),
                     key=lambda n: (n.span.start_line, n.qualname))
    calls = [done for call, done in loaded.calls if call.caller_key.split("::", 1)[0] == path]
    return {
        "record": record,
        "errors": list(module.attrs.get("errors") or []) if module else [],  # type: ignore[call-overload]
        "skipped_reason": module.attrs.get("skipped_reason") if module else None,
        "symbols": [{"node": n, "depth": n.qualname.count(".")} for n in symbols],
        "starts": {n.span.start_line: n for n in reversed(symbols)},  # outermost wins a tie
        "uses": _neighbours(loaded, path, outgoing=True),
        "used_by": _neighbours(loaded, path, outgoing=False),
        "calls": {"total": len(calls), "resolved": sum(calls)},
    }


def _neighbours(loaded: Loaded, path: str, outgoing: bool) -> list[dict[str, Any]]:
    """Other files this file uses (or is used by), with the edge count and best level."""
    count: Counter[str] = Counter()
    best: dict[str, float] = {}
    for link in loaded.links:
        here, other = ((link.src_path, link.dst_path) if outgoing
                       else (link.dst_path, link.src_path))
        if here == path:
            count[other] += 1
            best[other] = max(best.get(other, 0.0), link.edge.confidence)
    return [
        {"path": other, "count": n, "level": level(best[other])}
        for other, n in sorted(count.items(), key=lambda item: (-item[1], item[0]))
    ]


def symbol_page(loaded: Loaded, key: str) -> dict[str, Any] | None:
    """One symbol with what it uses, what uses it, and the calls that got no edge."""
    node = loaded.by_key.get(key)
    if node is None:
        return None
    unresolved = [call for call, done in loaded.calls if call.caller_key == key and not done]
    return {
        "node": node,
        "owner": loaded.by_key.get(node.owner_key) if node.owner_key else None,
        "members": sorted((n for n in loaded.nodes.values() if n.owner_key == key
                           and n.kind in SYMBOL_KINDS), key=lambda n: n.span.start_line),
        "uses": _relations(loaded, loaded.out_edges.get(node.id, []), outgoing=True),
        "used_by": _relations(loaded, loaded.in_edges.get(node.id, []), outgoing=False),
        "unresolved": sorted(unresolved, key=lambda call: call.line)[:MAX_ROWS],
        "unresolved_total": len(unresolved),
    }


def _relations(loaded: Loaded, edges: list[Edge], outgoing: bool) -> dict[str, Any]:
    """Edges of one symbol as rows, surest first, with counts per confidence level."""
    wanted = [e for e in edges if e.kind in RELATION_KINDS]
    wanted.sort(key=lambda e: (-e.confidence, str(e.kind), e.line or 0))
    rows = []
    for edge in wanted[:MAX_ROWS]:
        other = loaded.nodes.get(edge.dst_id if outgoing else edge.src_id)
        if other is not None:
            rows.append({"other": other, "kind": str(edge.kind),
                         "resolution": str(edge.resolution), "confidence": edge.confidence,
                         "level": level(edge.confidence), "line": edge.line})
    levels = Counter(level(e.confidence) for e in wanted)
    return {"total": len(wanted), "rows": rows, "levels": {name: levels[name] for name in LEVELS}}


def search(loaded: Loaded, ranked: list[Node], query: str) -> list[Node]:
    """Search results: full-text hits first, then names that merely contain the query.

    Full-text search matches whole words, so `gate` does not find `apply_gate`. The
    second pass finds those, shortest name first, and never repeats a full-text hit.
    """
    wanted = query.strip().lower()
    hits = [n for n in ranked if n.kind in SYMBOL_KINDS or n.kind is NodeKind.MODULE]
    if not wanted:
        return hits
    seen = {n.id for n in hits}
    partial = [
        n for n in loaded.nodes.values()
        if n.id not in seen and wanted in _search_name(n).lower()
        and (n.kind in SYMBOL_KINDS or n.kind is NodeKind.MODULE)
    ]
    partial.sort(key=lambda n: (len(_search_name(n)), n.key))
    return (hits + partial)[:MAX_HITS]


def _search_name(node: Node) -> str:
    """What a partial match is tried against: a file's path, a symbol's name."""
    return node.path if node.kind is NodeKind.MODULE else node.name
