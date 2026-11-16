"""The facts on the impact page: an `ImpactResult` turned into rows for a template.

The engine (`impact/engine.py`) does the ranking. This module only arranges its answer:
the test files to run, the other files the change reaches, and for each the evidence
path, with every key looked up so the page can link it.
"""

from __future__ import annotations

from typing import Any

from codeatlas.impact.models import Evidence, ImpactResult, Target, TestPick
from codeatlas.models import Node, NodeKind
from codeatlas.web.data import Loaded

MAX_CHANGED = 40
MAX_TESTS = 100
MAX_FILES = 40
MAX_SYMBOLS_PER_FILE = 5

# What each signal of the engine means, in the words the page uses.
SIGNALS = {
    "graph": "reached through calls and imports",
    "import": "imports a changed file",
    "cochange": "changed together in the past",
    "tests": "a test of something reached",
    "changed": "edited by the change",
}


def impact_view(
    loaded: Loaded, result: ImpactResult, threshold: float, test_files: set[str]
) -> dict[str, Any]:
    """Everything the page shows about one result.

    `threshold` is the engine's cut-off for a test worth running; `test_files` is every
    test file of the snapshot, so the page can say how many are skipped.
    """
    picks = result.test_files()
    run = [p for p in picks if p.score >= threshold]
    test_paths = {p.path for p in result.tests}
    others = [t for t in result.targets if t.path not in test_paths]
    files = _by_file(loaded, others)
    selected = {p.path for p in run} & test_files
    return {
        "changed": [_named(loaded, key) for key in result.changed[:MAX_CHANGED]],
        "changed_total": len(result.changed),
        "threshold": threshold,
        "tests": [_row(loaded, p) for p in run[:MAX_TESTS]],
        "tests_run": len(run),
        "tests_weaker": len(picks) - len(run),
        "test_files": len(test_files),
        "skipped_share": 1 - len(selected) / len(test_files) if test_files else None,
        "files": files[:MAX_FILES],
        "files_total": len(files),
        "targets_total": len(others),
        "warnings": list(result.warnings),
    }


def _by_file(loaded: Loaded, targets: list[Target]) -> list[dict[str, Any]]:
    """Targets grouped by file, the file with the highest score first.

    Targets arrive ranked, so the first one seen for a file is its best.
    """
    groups: dict[str, dict[str, Any]] = {}
    for target in targets:
        group = groups.setdefault(target.path, {"path": target.path, "score": target.score,
                                                "symbols": [], "count": 0})
        group["count"] += 1
        if len(group["symbols"]) < MAX_SYMBOLS_PER_FILE:
            group["symbols"].append(_row(loaded, target))
    return list(groups.values())


def _row(loaded: Loaded, item: Target | TestPick) -> dict[str, Any]:
    best = item.evidence[0] if item.evidence else None
    return {
        "path": item.path,
        "score": item.score,
        "name": _named(loaded, item.key),
        "why": _why(loaded, best) if best else None,
        "also": [SIGNALS.get(e.signal, e.signal) for e in item.evidence[1:]],
    }


def _why(loaded: Loaded, evidence: Evidence) -> dict[str, Any]:
    """One piece of evidence: what kind it is and the path from the change outwards."""
    hops = [{**_named(loaded, hop.key), "kind": hop.kind, "confidence": hop.confidence}
            for hop in evidence.path]
    return {"signal": SIGNALS.get(evidence.signal, evidence.signal), "score": evidence.score,
            "hops": hops, "detail": "" if evidence.signal == "changed" else evidence.detail}


def _named(loaded: Loaded, key: str) -> dict[str, Any]:
    """A key as something to show and link: the node when the snapshot has it."""
    node: Node | None = loaded.by_key.get(key)
    if node is None:
        return {"key": key, "node": None, "label": key}
    label = node.path if node.kind is NodeKind.MODULE else (node.qualname or node.name)
    return {"key": key, "node": node, "label": label}
