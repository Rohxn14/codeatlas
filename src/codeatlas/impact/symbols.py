"""Turn changed files and line ranges into the symbols they touch."""

from __future__ import annotations

from collections.abc import Sequence

from codeatlas.impact.models import Change
from codeatlas.models import Node, NodeKind
from codeatlas.store import GraphStore

SYMBOL_KINDS = frozenset({NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.INTERFACE, NodeKind.TEST})


def changed_nodes(
    store: GraphStore, snapshot_id: str, changes: Sequence[Change]
) -> tuple[list[Node], list[str]]:
    """The nodes the changes touch, and a warning for everything that could not be mapped."""
    found: dict[str, Node] = {}
    warnings: list[str] = []
    for change in changes:
        for node in _map_change(store, snapshot_id, change, warnings):
            found.setdefault(node.id, node)
    return list(found.values()), warnings


def _map_change(
    store: GraphStore, snapshot_id: str, change: Change, warnings: list[str]
) -> list[Node]:
    nodes: list[Node] = []
    for key in change.symbol_keys:
        matches = store.nodes_by_key(key, snapshot_id)
        if matches:
            nodes.append(matches[0])
        else:
            warnings.append(f"symbol {key} is not in the snapshot")
    if change.symbol_keys:
        return nodes
    module = store.module_for_path(snapshot_id, change.path)
    if module is None:
        warnings.append(f"{change.path} is not in the snapshot (new, ignored or outside it)")
        return []
    symbols = [n for n in store.nodes_in_file(snapshot_id, change.path)
               if n.kind in SYMBOL_KINDS]
    if not symbols:
        warnings.append(f"{change.path} has no symbols ({module.language}); using the file")
        return [module]
    if not change.ranges:
        return [module, *symbols]
    return _nodes_for_ranges(module, symbols, change.ranges)


def _nodes_for_ranges(
    module: Node, symbols: list[Node], ranges: tuple[tuple[int, int], ...]
) -> list[Node]:
    """Innermost symbol per changed line, or the module for lines outside every symbol.

    The innermost symbol only changes at a symbol's first line or the line after its
    last, so testing the range start and those boundaries inside the range is exact
    without visiting every line.
    """
    hit: dict[str, Node] = {}
    for first, last in ranges:
        found: dict[str, Node] = {}
        points = {first}
        for s in symbols:
            for boundary in (s.span.start_line, s.span.end_line + 1):
                if first < boundary <= last:
                    points.add(boundary)
        for line in points:
            node = _innermost(symbols, line)
            if node is not None:
                found.setdefault(node.id, node)
        # Blank lines and comments between symbols belong to no one; a range that touches
        # no symbol at all is a change to the file's top level.
        for node in found.values() or [module]:
            hit.setdefault(node.id, node)
    return list(hit.values())


def _innermost(symbols: list[Node], line: int) -> Node | None:
    best: Node | None = None
    for s in symbols:
        if s.span.start_line <= line <= s.span.end_line:
            width = s.span.end_line - s.span.start_line
            if best is None or width < best.span.end_line - best.span.start_line:
                best = s
    return best
