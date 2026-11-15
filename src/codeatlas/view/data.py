"""The JSON the viewer embeds: a snapshot read from the store, trimmed to a size cap.

Nothing is dropped silently: whatever the cap or `--focus` leaves out is counted in the
`omitted` section, which the page shows with the way to see it.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from codeatlas.models import Edge, EdgeKind, Node, NodeKind
from codeatlas.store import GraphStore

MAX_NODES = 30_000
MAX_UNRESOLVED_CALLS = 20_000
_DOC_CHARS = 600


def latest_snapshot_id(db_path: Path) -> str | None:
    """The most recently indexed snapshot in the database, whatever its repository."""
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT id FROM snapshots ORDER BY indexed_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return str(row[0]) if row else None


def build_view_data(
    store: GraphStore,
    snapshot_id: str,
    report: dict[str, Any] | None = None,
    focus: str = "",
    max_nodes: int = MAX_NODES,
) -> dict[str, Any]:
    """Everything the page shows. `focus` keeps files under one path prefix."""
    snapshot = store.get_snapshot(snapshot_id)
    if snapshot is None:
        raise KeyError(f"no snapshot {snapshot_id!r}")
    focus = normalise_focus(focus)
    nodes = store.nodes(snapshot_id)
    edges = store.edges(snapshot_id)
    files = store.files(snapshot_id)
    calls = store.raw_calls(snapshot_id)

    kept_files, kept = _select(nodes, focus, max_nodes)
    index = {n.id: i for i, n in enumerate(kept)}
    kept_edges = [e for e in edges if e.src_id in index and e.dst_id in index]
    unresolved = [(c, r) for c, r in calls if not r]
    key_index = {n.key: i for i, n in enumerate(kept)}
    shown_calls = [
        {"n": key_index[c.caller_key], "t": c.callee_text, "l": c.line}
        for c, _ in unresolved
        if c.caller_key in key_index
    ][:MAX_UNRESOLVED_CALLS]

    return {
        "snapshot": {**_plain(snapshot), "limits_hit": list(snapshot.limits_hit)},
        "focus": focus,
        "census": census(files, nodes, calls),
        "packages": packages(nodes, edges),
        "files": [
            {"path": f.path, "language": f.language, "tier": str(f.tier)}
            for f in files
            if f.path in kept_files
        ],
        "nodes": [_node(n) for n in kept],
        "edges": [_edge(e, index) for e in kept_edges],
        "unresolved_calls": shown_calls,
        "omitted": {
            "files": len(files) - len(kept_files),
            "nodes": len(nodes) - len(kept),
            "edges": len(edges) - len(kept_edges),
            "unresolved_calls": len(unresolved) - len(shown_calls),
            "capped": _capped(nodes, focus, max_nodes),
            "max_nodes": max_nodes,
        },
        "problems": problems(nodes, report),
        "report": report,
    }


MAX_IMPACT_TARGETS = 30


def impact_block(result: Any, top: int = MAX_IMPACT_TARGETS) -> dict[str, Any]:
    """The page's impact section: changed keys, then the top targets with their best evidence.

    Keys, not node indexes, because a target may sit outside the nodes the page kept;
    the page shows those as plain text instead of a link.
    """
    return {
        "changed": list(result.changed),
        "targets": [
            {"key": t.key, "kind": str(t.kind), "score": round(t.score, 3),
             "signal": t.evidence[0].signal if t.evidence else ""}
            for t in result.targets[:top]
        ],
        "total": len(result.targets),
        "warnings": list(result.warnings),
    }


def _plain(snapshot: Any) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "repo": snapshot.repo,
        "commit_sha": snapshot.commit_sha,
        "indexed_at": snapshot.indexed_at,
        "indexer_version": snapshot.indexer_version,
        "source": snapshot.source,
    }


def normalise_focus(focus: str) -> str:
    """`backend\\`, `./backend/` and `backend` all mean the folder `backend`."""
    focus = focus.strip().replace("\\", "/")
    while focus.startswith("./"):
        focus = focus[2:]
    return focus.strip("/")


def focus_matches(store: GraphStore, snapshot_id: str, focus: str) -> bool:
    """True when some file of the snapshot is the focus or lies under it."""
    focus = normalise_focus(focus)
    return not focus or any(
        f.path == focus or f.path.startswith(focus + "/") for f in store.files(snapshot_id)
    )


def _in_focus(node: Node, focus: str) -> bool:
    if not focus:
        return True
    return node.path == focus or node.path.startswith(focus + "/")


def _focused(nodes: list[Node], focus: str) -> list[Node]:
    """Nodes under the focus, plus path-less ones (packages, externals, routes)."""
    return [n for n in nodes if not n.path or _in_focus(n, focus)]


def _capped(nodes: list[Node], focus: str, max_nodes: int) -> bool:
    return len(_focused(nodes, focus)) > max_nodes


def _select(nodes: list[Node], focus: str, max_nodes: int) -> tuple[set[str], list[Node]]:
    """Path-less nodes (packages, externals) up to half the cap, then whole files in path
    order while they fit. A file too big to fit is skipped, not a reason to stop: the
    smaller files after it still appear."""
    pathless = [n for n in nodes if not n.path][: max_nodes // 2]
    by_file: dict[str, list[Node]] = {}
    for n in nodes:
        if n.path and _in_focus(n, focus):
            by_file.setdefault(n.path, []).append(n)
    kept = list(pathless)
    files: set[str] = set()
    for path in sorted(by_file):
        group = by_file[path]
        if len(kept) + len(group) > max_nodes:
            continue
        kept += group
        files.add(path)
    return files, kept


def _node(n: Node) -> dict[str, Any]:
    return {
        "key": n.key,
        "kind": str(n.kind),
        "language": n.language,
        "name": n.name,
        "qualname": n.qualname,
        "path": n.path,
        "start": n.span.start_line,
        "end": n.span.end_line,
        "signature": n.signature,
        "doc": (n.docstring or "")[:_DOC_CHARS] or None,
        "errors": _list(n.attrs.get("errors")),
        "skipped": n.attrs.get("skipped_reason"),
        "ecosystem": n.attrs.get("ecosystem"),
    }


def _list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _edge(e: Edge, index: dict[str, int]) -> dict[str, Any]:
    return {
        "s": index[e.src_id],
        "d": index[e.dst_id],
        "kind": str(e.kind),
        "res": str(e.resolution),
        "conf": round(e.confidence, 3),
        "line": e.line,
    }


def census(files: list[Any], nodes: list[Node], calls: list[Any]) -> list[dict[str, Any]]:
    """One row per (language, tier) over the whole snapshot, not just the shown part."""
    language_of = {f.path: f.language for f in files}
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for f in files:
        row = rows.setdefault(
            (f.language, str(f.tier)),
            {"language": f.language, "tier": str(f.tier), "files": 0, "symbols": 0,
             "calls": 0, "resolved": 0, "errors": 0},
        )
        row["files"] += 1
    tier_of_language: dict[str, str] = {}
    for (language, tier) in rows:
        tier_of_language.setdefault(language, tier)
    for n in nodes:
        row = rows.get((n.language, tier_of_language.get(n.language, "")))
        if row is None:
            continue
        if n.kind in (NodeKind.CLASS, NodeKind.INTERFACE, NodeKind.FUNCTION, NodeKind.TEST):
            row["symbols"] += 1
        if n.kind is NodeKind.MODULE and n.attrs.get("errors"):
            row["errors"] += 1
    for call, resolved in calls:
        language = language_of.get(call.caller_key.split("::", 1)[0])
        row = rows.get((language or "", tier_of_language.get(language or "", "")))
        if row is not None:
            row["calls"] += 1
            row["resolved"] += 1 if resolved else 0
    return sorted(rows.values(), key=lambda r: (-r["files"], r["language"], r["tier"]))


def packages(nodes: list[Node], edges: list[Edge]) -> list[dict[str, Any]]:
    packages = {n.id: n for n in nodes if n.kind is NodeKind.PACKAGE}
    file_counts: Counter[str] = Counter(
        e.src_id for e in edges if e.kind is EdgeKind.CONTAINS and e.src_id in packages
    )
    deps: dict[str, list[str]] = {}
    for e in edges:
        if e.kind is EdgeKind.DEPENDS_ON and e.src_id in packages:
            target = packages.get(e.dst_id)
            deps.setdefault(e.src_id, []).append(target.name if target else e.dst_id)
    return [
        {
            "name": p.name,
            "key": p.key,
            "ecosystem": p.attrs.get("ecosystem"),
            "role": p.attrs.get("role", "package"),
            "files": file_counts[p.id],
            "depends_on": sorted(deps.get(p.id, [])),
        }
        for p in sorted(packages.values(), key=lambda p: p.key)
    ]


def problems(nodes: list[Node], report: dict[str, Any] | None) -> dict[str, Any]:
    with_errors = [
        {"path": n.path, "errors": list(n.attrs["errors"])}  # type: ignore[call-overload]
        for n in nodes
        if n.kind is NodeKind.MODULE and isinstance(n.attrs.get("errors"), list)
    ]
    skipped = [
        {"path": n.path, "reason": str(n.attrs["skipped_reason"])}
        for n in nodes
        if n.kind is NodeKind.MODULE and n.attrs.get("skipped_reason")
    ]
    saved = (report or {}).get("problems", {})
    return {
        "files_with_errors": with_errors,
        "skipped_files": skipped,
        "languages_without_resolver": saved.get("languages_without_resolver", []),
        "failures": saved.get("plugin_and_resolver_failures", []),
        "dropped_edges": ((report or {}).get("edges") or {}).get("dropped", {}),
        "not_entered": (((report or {}).get("files") or {}).get("not_entered") or {}).get(
            "paths", []),
        "report_missing": report is None,
    }
