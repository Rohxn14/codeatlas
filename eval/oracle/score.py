"""Score a CodeAtlas graph export against hand labels or a SCIP oracle.

    python -m eval.oracle.score --predicted export.json --truth expected_graph.json

Edges are compared as (src_key, dst_key, kind) triples. Only part of a prediction can be
judged against a given truth file, so before counting, predicted edges are set aside
when:

- their kind does not appear in the truth (an oracle only knows `calls`);
- an endpoint is not a truth node (calls into third-party code, package nodes the
  truth does not list): the truth says nothing about them either way;
- they start at a call site the truth marks unresolvable (`HANDLERS[name](...)`):
  any target there is a guess, reported apart, neither right nor wrong.

The rest gives precision, recall and F1 per edge kind, per language and per resolution,
a calibration table for CALLS confidence, and the worst misses for debugging.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.oracle.graph import Graph, GraphEdge, language_of_path, load_graph, path_of_key

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
# Calibration bins for CALLS confidence: [low, high), the last one closed at 1.0.
BINS: tuple[tuple[float, float], ...] = ((0.0, 0.3), (0.3, 0.6), (0.6, 0.9), (0.9, 1.0))
WORST = 20


@dataclass(frozen=True, slots=True)
class Split:
    """Predicted edges sorted into what can be judged and what cannot."""

    scored: list[GraphEdge]
    kind_not_in_truth: Counter[str]
    outside_truth_nodes: Counter[str]
    on_unresolvable: list[GraphEdge]


def dedupe(edges: Iterable[GraphEdge]) -> list[GraphEdge]:
    """One edge per triple; the most confident copy wins, then the earliest line."""
    best: dict[tuple[str, str, str], GraphEdge] = {}
    for edge in edges:
        current = best.get(edge.triple)
        if current is None or (-edge.confidence, edge.line or 0) < (
            -current.confidence, current.line or 0
        ):
            best[edge.triple] = edge
    return list(best.values())


def split_predicted(predicted: Graph, truth: Graph) -> Split:
    kinds = {e.kind for e in truth.edges}
    dynamic = {(u.src_key, u.line) for u in truth.unresolvable}
    scored: list[GraphEdge] = []
    other_kind: Counter[str] = Counter()
    outside: Counter[str] = Counter()
    guesses: list[GraphEdge] = []
    for edge in dedupe(predicted.edges):
        if edge.kind not in kinds:
            other_kind[edge.kind] += 1
        elif edge.src_key not in truth.nodes or edge.dst_key not in truth.nodes:
            outside[edge.kind] += 1
        elif edge.kind == "calls" and (edge.src_key, edge.line) in dynamic:
            guesses.append(edge)
        else:
            scored.append(edge)
    return Split(scored, other_kind, outside, guesses)


def prf(tp: int, fp: int, fn: int) -> dict[str, float | int | None]:
    """Precision, recall and F1; None where the denominator is zero."""
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def grouped(
    predicted: Sequence[GraphEdge],
    truth: Sequence[GraphEdge],
    group: Callable[[GraphEdge], str],
) -> dict[str, dict[str, float | int | None]]:
    """Precision, recall and F1 for each value of `group`."""
    truth_triples = {e.triple for e in truth}
    pred_triples = {e.triple for e in predicted}
    names = sorted({group(e) for e in [*predicted, *truth]})
    out = {}
    for name in names:
        p = [e for e in predicted if group(e) == name]
        t = [e for e in truth if group(e) == name]
        tp = sum(e.triple in truth_triples for e in p)
        fn = sum(e.triple not in pred_triples for e in t)
        out[name] = prf(tp, len(p) - tp, fn)
    return out


def by_resolution(
    predicted: Sequence[GraphEdge], truth: Sequence[GraphEdge]
) -> dict[str, dict[str, float | int | None]]:
    """Precision per resolution, and how much of the truth each resolution recovers.

    A missing edge has no resolution, so recall cannot be split exactly; `recall_share`
    is this resolution's true positives over all truth edges of the same kinds.
    """
    truth_triples = {e.triple for e in truth}
    out = {}
    for name in sorted({e.resolution for e in predicted}):
        p = [e for e in predicted if e.resolution == name]
        kinds = {e.kind for e in p}
        tp = sum(e.triple in truth_triples for e in p)
        relevant = sum(e.kind in kinds for e in truth)
        row = prf(tp, len(p) - tp, 0)
        row.pop("fn")
        row["recall_share"] = tp / relevant if relevant else None
        row.pop("recall")
        row.pop("f1")
        out[name] = row
    return out


def calibration(
    predicted: Sequence[GraphEdge], truth: Sequence[GraphEdge]
) -> list[dict[str, float | int | str | None]]:
    """For predicted CALLS edges binned by confidence: the share that are true."""
    truth_triples = {e.triple for e in truth}
    calls = [e for e in predicted if e.kind == "calls"]
    rows = []
    for i, (low, high) in enumerate(BINS):
        last = i == len(BINS) - 1
        inside = [e for e in calls if low <= e.confidence < high or (last and e.confidence == high)]
        true = sum(e.triple in truth_triples for e in inside)
        rows.append({
            "bin": f"{low:.1f}-{high:.1f}",
            "count": len(inside),
            "true": true,
            "share_true": true / len(inside) if inside else None,
            "mean_confidence": sum(e.confidence for e in inside) / len(inside) if inside else None,
        })
    return rows


def _describe(edge: GraphEdge) -> dict[str, object]:
    return {"kind": edge.kind, "src_key": edge.src_key, "dst_key": edge.dst_key,
            "file": path_of_key(edge.src_key), "line": edge.line,
            "confidence": edge.confidence, "resolution": edge.resolution}


def worst(
    predicted: Sequence[GraphEdge], truth: Sequence[GraphEdge], limit: int = WORST
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """False positives, most confident first; false negatives by kind, file and line."""
    truth_triples = {e.triple for e in truth}
    pred_triples = {e.triple for e in predicted}
    fps = sorted(
        (e for e in predicted if e.triple not in truth_triples),
        key=lambda e: (-e.confidence, e.kind, e.src_key, e.line or 0),
    )
    fns = sorted(
        (e for e in truth if e.triple not in pred_triples),
        key=lambda e: (e.kind, path_of_key(e.src_key), e.line or 0, e.dst_key),
    )
    return [_describe(e) for e in fps[:limit]], [_describe(e) for e in fns[:limit]]


def score(predicted: Graph, truth: Graph) -> dict[str, object]:
    split = split_predicted(predicted, truth)
    truth_edges = dedupe(truth.edges)
    pred = split.scored

    def language(edge: GraphEdge) -> str:
        node = truth.nodes.get(edge.src_key)
        return node.language if node else language_of_path(path_of_key(edge.src_key))

    totals = grouped(pred, truth_edges, lambda e: "all")["all"] if truth_edges else prf(0, 0, 0)
    false_positives, false_negatives = worst(pred, truth_edges)
    return {
        "overall": totals,
        "by_kind": grouped(pred, truth_edges, lambda e: e.kind),
        "by_language": grouped(pred, truth_edges, language),
        "by_resolution": by_resolution(pred, truth_edges),
        "calibration_calls": calibration(pred, truth_edges),
        "worst_false_positives": false_positives,
        "worst_false_negatives": false_negatives,
        "not_scored": {
            "kind_not_in_truth": dict(split.kind_not_in_truth),
            "endpoint_not_in_truth": dict(split.outside_truth_nodes),
            "guesses_on_unresolvable_calls": [_describe(e) for e in split.on_unresolvable],
        },
    }


# Report --------------------------------------------------------------------------------


def _fmt(value: object) -> str:
    return f"{value:.3f}" if isinstance(value, float) else ("-" if value is None else str(value))


def _table(title: str, rows: dict[str, dict[str, object]], columns: Sequence[str]) -> list[str]:
    width = max([len(title), *(len(n) for n in rows)])
    lines = [f"{title:<{width}}  " + "  ".join(f"{c:>12}" for c in columns)]
    for name, row in rows.items():
        lines.append(f"{name:<{width}}  " + "  ".join(f"{_fmt(row.get(c)):>12}" for c in columns))
    return lines


def render(result: dict[str, Any]) -> str:
    """The result as plain-text tables for the terminal."""
    metrics = ("precision", "recall", "f1", "tp", "fp", "fn")
    lines = _table("overall", {"all": result["overall"]}, metrics)
    for name in ("by_kind", "by_language"):
        lines += ["", *_table(name, result[name], metrics)]
    lines += ["", *_table("by_resolution", result["by_resolution"],
                          ("precision", "recall_share", "tp", "fp"))]
    calib = {str(r["bin"]): r for r in result["calibration_calls"]}
    lines += ["", *_table("calls confidence", calib,
                          ("count", "true", "share_true", "mean_confidence"))]
    for name in ("worst_false_positives", "worst_false_negatives"):
        lines += ["", f"{name}:"]
        for e in result[name]:
            lines.append(f"  {e['kind']:<10} {e['file']}:{e['line']}  {e['src_key']} -> "
                         f"{e['dst_key']}  ({e['resolution']} {_fmt(e['confidence'])})")
    lines += ["", f"not scored: {json.dumps(result['not_scored'], default=str)[:600]}"]
    return "\n".join(lines)


def save(result: dict[str, object], truth_path: Path, out_dir: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"graph_score_{truth_path.stem}_{stamp}.json"
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score a graph export against ground truth.")
    parser.add_argument("--predicted", type=Path, required=True, help="CodeAtlas graph export")
    parser.add_argument("--truth", type=Path, required=True,
                        help="expected_graph.json or an oracle_*.json file")
    parser.add_argument("--out-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)

    result = score(load_graph(args.predicted), load_graph(args.truth))
    result["inputs"] = {"predicted": str(args.predicted), "truth": str(args.truth)}
    print(render(result))
    print(f"\nsaved {save(result, args.truth, args.out_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
