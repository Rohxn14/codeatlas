"""Part 4 of the repository layer: one dictionary describing what the layer found.

The CLI prints it and the acceptance suite compares it across repositories. Everything
that can be read from the nodes and edges is read from them, so the summary describes
what will actually be stored. Facts no edge records (commits read, what each co-change
filter removed) come from the analyzers' own `report`, when the analyzers are passed in.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from codeatlas.indexer.adapter import RepoAnalyzer
from codeatlas.models import Edge, EdgeKind, FileRecord, Node, NodeKind, Resolution
from codeatlas.repo.test_conventions import classify


def summarize(
    files: Sequence[FileRecord],
    nodes: Sequence[Node],
    edges: Sequence[Edge],
    analyzers: Sequence[RepoAnalyzer] = (),
) -> dict[str, object]:
    reports = {a.name: getattr(a, "report", {}) for a in analyzers}
    return {
        "languages": _census(files),
        "packages": _packages(nodes, edges),
        "tests": _tests(files, edges),
        "cochange": _cochange(edges, reports.get("cochange", {})),
    }


def _census(files: Sequence[FileRecord]) -> list[dict[str, object]]:
    """One row per (language, tier), largest first, like `codeatlas scan`."""
    counts: Counter[tuple[str, str]] = Counter()
    sizes: Counter[tuple[str, str]] = Counter()
    for record in files:
        key = (record.language, str(record.tier))
        counts[key] += 1
        sizes[key] += record.size_bytes
    ordered = sorted(counts, key=lambda k: (-sizes[k], k))
    return [
        {"language": k[0], "tier": k[1], "files": counts[k], "bytes": sizes[k]} for k in ordered
    ]


def _packages(nodes: Sequence[Node], edges: Sequence[Edge]) -> dict[str, object]:
    packages = [n for n in nodes if n.kind is NodeKind.PACKAGE]
    by_ecosystem = Counter(str(p.attrs.get("ecosystem")) for p in packages)
    warnings: list[object] = []
    for package in packages:
        found = package.attrs.get("warnings")
        if isinstance(found, list):
            warnings.extend(found)
    return {
        "total": len(packages),
        "by_ecosystem": dict(sorted(by_ecosystem.items())),
        "implicit": any(p.attrs.get("implicit") for p in packages),
        "internal_dependencies": sum(1 for e in edges if e.kind is EdgeKind.DEPENDS_ON),
        "warnings": warnings,
    }


def _tests(files: Sequence[FileRecord], edges: Sequence[Edge]) -> dict[str, object]:
    tests = sorted(f.path for f in files if classify(f.path, f.language) is not None)
    targets: Counter[str] = Counter(
        _module_path(e.src_id)
        for e in edges
        if e.kind is EdgeKind.TESTS and e.resolution is Resolution.CONVENTION
    )
    paired = [t for t in tests if targets[t]]
    return {
        "test_files": len(tests),
        "paired": len(paired),
        "pairing_rate": round(len(paired) / len(tests), 3) if tests else None,
        "ambiguous": sum(1 for t in paired if targets[t] > 1),
        "unpaired": [t for t in tests if not targets[t]],
    }


def _cochange(edges: Sequence[Edge], report: dict[str, object]) -> dict[str, object]:
    cochange = [e for e in edges if e.kind is EdgeKind.CO_CHANGES]
    summary: dict[str, object] = {
        "edges": len(cochange),
        "files_with_edges": len({e.src_id for e in cochange}),
    }
    for key in (
        "status", "commits_read", "commits_analysed", "commits_skipped_large",
        "files_removed", "history_truncated", "shallow", "targets_over_limit",
    ):
        if key in report:
            summary[key] = report[key]
    return summary


def _module_path(node_id: str) -> str:
    """`repo@sha/src/a.py::` -> `src/a.py`; snapshot ids hold no slash (contract section 4)."""
    return node_id.partition("/")[2].removesuffix("::")
