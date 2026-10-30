"""Traversals over the NetworkX view: who calls what, and what reaches a change."""

from collections.abc import Iterable

import networkx as nx

from codeatlas.models import EdgeKind


def callers(
    g: nx.MultiDiGraph, node_id: str, depth: int = 1, min_confidence: float = 0.0
) -> dict[str, float]:
    """Nodes that call `node_id` within `depth` hops, with their best path confidence."""
    return _walk(g, [node_id], {str(EdgeKind.CALLS)}, depth, min_confidence, reverse=True)


def callees(
    g: nx.MultiDiGraph, node_id: str, depth: int = 1, min_confidence: float = 0.0
) -> dict[str, float]:
    """Nodes `node_id` calls within `depth` hops, with their best path confidence."""
    return _walk(g, [node_id], {str(EdgeKind.CALLS)}, depth, min_confidence, reverse=False)


def reverse_reach(
    g: nx.MultiDiGraph,
    node_ids: Iterable[str],
    kinds: Iterable[EdgeKind] | None = None,
    depth: int | None = None,
) -> dict[str, float]:
    """Every node with a path to any of `node_ids`, and that path's best confidence.

    A path's confidence is the product of its edge confidences, so one weak guess
    anywhere weakens the whole chain. `kinds=None` follows every edge kind and
    `depth=None` places no limit on path length.
    """
    wanted = None if kinds is None else {str(k) for k in kinds}
    return _walk(g, list(node_ids), wanted, depth, 0.0, reverse=True)


def _walk(
    g: nx.MultiDiGraph,
    starts: list[str],
    kinds: set[str] | None,
    depth: int | None,
    min_confidence: float,
    reverse: bool,
) -> dict[str, float]:
    """Best product of confidences over paths of at most `depth` edges.

    Round by round, like Bellman-Ford: round i extends only the nodes whose best
    score improved in round i - 1, so after round i every path of up to i edges has
    been tried. Confidences are at most 1, so going round a cycle never improves a
    score, and the walk stops even with no depth limit. Start nodes are left out of
    the result.
    """
    best: dict[str, float] = {s: 1.0 for s in starts if s in g}
    frontier = set(best)
    rounds = 0
    while frontier and (depth is None or rounds < depth):
        rounds += 1
        # Scores as they stood when the round began, so a node improved earlier in this
        # round cannot extend a path by two edges in one round.
        start_scores = {node: best[node] for node in frontier}
        improved: set[str] = set()
        for node, base in start_scores.items():
            for neighbour, confidence in _steps(g, node, kinds, min_confidence, reverse):
                score = base * confidence
                if score > best.get(neighbour, 0.0):
                    best[neighbour] = score
                    improved.add(neighbour)
        frontier = improved
    for s in starts:
        best.pop(s, None)
    return best


def _steps(
    g: nx.MultiDiGraph, node: str, kinds: set[str] | None, min_confidence: float, reverse: bool
) -> Iterable[tuple[str, float]]:
    """One hop from `node`, against edge direction when `reverse` is set."""
    edges = g.in_edges(node, data=True) if reverse else g.out_edges(node, data=True)
    for src, dst, data in edges:
        if kinds is not None and data["kind"] not in kinds:
            continue
        if data["confidence"] < min_confidence:
            continue
        yield (src if reverse else dst), data["confidence"]
