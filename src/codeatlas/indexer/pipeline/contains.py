"""CONTAINS edges inside each file, the same way for every tier (decision D-14).

The contract makes the pipeline, not each adapter, responsible for containment, so a
method is inside its class whichever tier parsed it.
"""

from __future__ import annotations

from collections.abc import Iterable

from codeatlas.models import Edge, EdgeKind, Node, NodeKind, ParseResult, Resolution


def contains_edges(results: Iterable[ParseResult]) -> list[Edge]:
    edges: list[Edge] = []
    for result in results:
        if not result.nodes:
            continue
        module, rest = result.nodes[0], result.nodes[1:]
        by_qualname = {n.qualname: n for n in rest}
        by_key = {n.key: n for n in rest}
        for node in rest:
            parent = _parent(node, by_qualname, by_key) or module
            edges.append(Edge(parent.id, node.id, EdgeKind.CONTAINS, 1.0, Resolution.STRUCTURAL))
    return edges


def _parent(node: Node, by_qualname: dict[str, Node], by_key: dict[str, Node]) -> Node | None:
    """The node that contains `node` in the same file, or None for the module.

    A method names its class in `owner_key`. Otherwise the qualname says it: the part
    before the last `.` (Function -> nested function, Class -> nested class). A `#`
    straight after a `.` is part of a name (`A.#secret`, D-16), and a trailing `#hash`
    is the duplicate-name suffix, not a level, so neither changes the split. TypeScript
    test names (`A > b`) have no `.` and belong to the module.
    """
    if node.owner_key is not None and node.owner_key in by_key:
        return by_key[node.owner_key]
    if node.kind is NodeKind.TEST and " > " in node.qualname:
        return None
    head, dot, _ = _strip_suffix(node.qualname).rpartition(".")
    if not dot or not head:
        return None
    return by_qualname.get(head)


def _strip_suffix(qualname: str) -> str:
    """`Square.label#98f3` -> `Square.label`; `A.#secret` stays as it is."""
    head, hash_mark, tail = qualname.rpartition("#")
    if hash_mark and head and not head.endswith(".") and "." not in tail:
        return head
    return qualname
