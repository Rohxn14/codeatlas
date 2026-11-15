"""The facts on the coverage page, read from the store and counted here.

Nothing on the page is written by a model: every number is a count of rows in one
snapshot. The page states what was not analysed next to what was, so a reader can tell a
small repository from a badly covered one.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from codeatlas.models import Edge, EdgeKind, FileRecord, Node, NodeKind, Tier
from codeatlas.view.data import census, packages, problems
from codeatlas.web.confidence import LEVELS, level
from codeatlas.web.data import Loaded

SYMBOL_KINDS = (NodeKind.CLASS, NodeKind.INTERFACE, NodeKind.FUNCTION, NodeKind.TEST)
# Containment is true by construction (a file contains its functions). Counting it would
# make the map look more certain than its calls and imports are.
_NOT_FOUND_BY_ANALYSIS = (EdgeKind.CONTAINS,)
MAX_PROBLEM_ROWS = 25


def build_overview(loaded: Loaded) -> dict[str, Any]:
    """Everything the coverage page shows for one snapshot."""
    snapshot, report = loaded.snapshot, loaded.report
    nodes, edges = list(loaded.nodes.values()), loaded.edges
    files, calls = loaded.files, loaded.calls
    languages = census(files, nodes, calls)
    resolved = sum(1 for _, done in calls if done)
    return {
        "snapshot": snapshot,
        "totals": {
            "files": len(files),
            "symbols": sum(1 for n in nodes if n.kind in SYMBOL_KINDS),
            "edges": len(edges),
            "languages": len({f.language for f in files}),
        },
        "tiers": tier_shares(files),
        "calls": {"total": len(calls), "resolved": resolved, "share": share(resolved, len(calls))},
        "languages": [{**row, "share": share(row["resolved"], row["calls"])} for row in languages],
        "packages": packages(nodes, edges),
        "trust": trust_rows(edges),
        "trust_total": trust_total(edges),
        "problems": problem_lists(nodes, report, list(snapshot.limits_hit)),
    }


def share(part: int, whole: int) -> float | None:
    """A share from 0 to 1, or None when there is nothing to take a share of."""
    return part / whole if whole else None


def tier_shares(files: list[FileRecord]) -> list[dict[str, Any]]:
    """Files per tier, always all three tiers in the same order, so the meter never shifts."""
    counts = Counter(f.tier for f in files)
    return [
        {"tier": str(tier), "files": counts[tier], "share": share(counts[tier], len(files)) or 0.0}
        for tier in (Tier.DEEP, Tier.STRUCTURAL, Tier.TEXT)
    ]


def trust_rows(edges: list[Edge]) -> list[dict[str, Any]]:
    """One row per edge kind: how many edges, and how many at each confidence level."""
    by_kind: dict[EdgeKind, Counter[str]] = {}
    for edge in edges:
        by_kind.setdefault(edge.kind, Counter())[level(edge.confidence)] += 1
    return [
        {
            "kind": str(kind),
            "total": sum(by_kind[kind].values()),
            "levels": {name: by_kind[kind][name] for name in LEVELS},
            "by_construction": kind in _NOT_FOUND_BY_ANALYSIS,
        }
        for kind in EdgeKind
        if kind in by_kind
    ]


def trust_total(edges: list[Edge]) -> dict[str, Any]:
    """The confidence meter: every edge found by analysis, split by level."""
    counts = Counter(level(e.confidence) for e in edges if e.kind not in _NOT_FOUND_BY_ANALYSIS)
    total = sum(counts.values())
    return {
        "total": total,
        "levels": [
            {"level": name, "count": counts[name], "share": share(counts[name], total) or 0.0}
            for name in LEVELS
        ],
    }


def problem_lists(
    nodes: list[Node], report: dict[str, Any] | None, limits_hit: list[str]
) -> dict[str, Any]:
    """What could not be analysed. Long lists are cut for the page, with the full count kept."""
    found = problems(nodes, report)
    lists = {
        "files_with_errors": found["files_with_errors"],
        "skipped_files": found["skipped_files"],
        "not_entered": [{"path": path} for path in found["not_entered"]],
    }
    return {
        **{name: _cut(rows) for name, rows in lists.items()},
        "languages_without_resolver": found["languages_without_resolver"],
        "failures": found["failures"],
        "dropped_edges": found["dropped_edges"],
        "skipped_by_reason": (((report or {}).get("files") or {}).get("skipped") or {}).get(
            "by_reason", {}),
        "limits_hit": limits_hit,
        "report_missing": found["report_missing"],
    }


def _cut(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"total": len(rows), "shown": rows[:MAX_PROBLEM_ROWS]}
