"""A layered layout for a small directed graph: which box goes in which row, in what order.

Written here rather than taken from a library so every step can be read (decision D-31).
The method is the classic one for dependency diagrams, in three steps:

1. Ignore the arrows that would make a cycle, lightest first, so the rest can be layered.
2. Put each box one row below the lowest box that points at it (users above, used below).
3. Reorder each row so boxes sit near the boxes they connect to, which shortens arrows.

Pure functions over names and weights; nothing here knows about files or SVG.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

Pair = tuple[str, str]
SWEEPS = 4


def acyclic_pairs(names: Iterable[str], weights: Mapping[Pair, int]) -> set[Pair]:
    """The pairs kept for layering: heaviest first, skipping any that would close a cycle.

    With `a -> b` weighing 10 and `b -> a` weighing 2, `a -> b` is kept, so `a` ends up
    above `b`. The skipped arrow is still drawn; it just points upwards.
    """
    reach: dict[str, set[str]] = {name: set() for name in names}
    kept: set[Pair] = set()
    for (src, dst), _ in sorted(weights.items(), key=lambda item: (-item[1], item[0])):
        if src == dst or src not in reach or dst not in reach:
            continue
        if _reaches(reach, dst, src):
            continue
        reach[src].add(dst)
        kept.add((src, dst))
    return kept


def _reaches(children: Mapping[str, set[str]], start: str, goal: str) -> bool:
    """Whether `goal` can be reached from `start` along kept arrows (depth-first)."""
    stack, seen = [start], {start}
    while stack:
        node = stack.pop()
        if node == goal:
            return True
        for child in children[node] - seen:
            seen.add(child)
            stack.append(child)
    return False


def assign_layers(names: Iterable[str], pairs: set[Pair]) -> dict[str, int]:
    """Row number per box: 0 when nothing points at it, else one below its lowest user."""
    parents: dict[str, list[str]] = {name: [] for name in names}
    for src, dst in pairs:
        parents[dst].append(src)
    layers: dict[str, int] = {}

    def layer(name: str) -> int:
        if name not in layers:
            layers[name] = 1 + max((layer(p) for p in parents[name]), default=-1)
        return layers[name]

    for name in parents:
        layer(name)
    return layers


def order_rows(layers: Mapping[str, int], pairs: set[Pair]) -> list[list[str]]:
    """Boxes per row, each row ordered by the average position of its neighbours.

    A few sweeps down and up are enough for diagrams of this size; the result is
    deterministic because ties fall back to the name.
    """
    rows: list[list[str]] = [[] for _ in range(max(layers.values(), default=-1) + 1)]
    for name in sorted(layers):
        rows[layers[name]].append(name)
    neighbours: dict[str, list[str]] = {name: [] for name in layers}
    for src, dst in pairs:
        neighbours[src].append(dst)
        neighbours[dst].append(src)
    for sweep in range(SWEEPS):
        order = rows if sweep % 2 == 0 else list(reversed(rows))
        for row in order:
            position = {name: i for r in rows for i, name in enumerate(r)}
            row.sort(key=lambda name: (_average(neighbours[name], position, name), name))
    return rows


def _average(names: list[str], position: Mapping[str, int], own: str) -> float:
    """The mean position of a box's neighbours; its own position when it has none."""
    if not names:
        return float(position[own])
    return sum(position[n] for n in names) / len(names)


def layered_rows(names: Iterable[str], weights: Mapping[Pair, int]) -> list[list[str]]:
    """The whole layout: rows of box names, top row first."""
    names = list(names)
    pairs = acyclic_pairs(names, weights)
    return order_rows(assign_layers(names, pairs), pairs)
