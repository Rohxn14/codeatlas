"""The architecture diagram: folders and files as boxes, arrows counted from real edges.

Nothing is drawn that is not in the store. An arrow from box A to box B exists because
at least one import, call, inheritance or HTTP link goes from a file in A to a file in
B, and `arrow_edges` lists exactly those edges. No model is involved (decision D-31).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from codeatlas.models import Edge, EdgeKind, FileRecord, Node, Tier
from codeatlas.web.confidence import LEVELS, level
from codeatlas.web.layout import layered_rows

# The edge kinds that mean "code here uses code there". Containment, tests-by-convention
# and co-change are other relations and would bury the structure.
ARROW_KINDS = (EdgeKind.IMPORTS, EdgeKind.CALLS, EdgeKind.INHERITS, EdgeKind.CALLS_HTTP,
               EdgeKind.REFERENCES)
MAX_BOXES = 40
MAX_ROW = 6
MAX_ARROW_EDGES = 200
MIN_ARROWS = 12
ARROWS_PER_BOX = 1.5

BOX_W, BOX_H = 168, 56
GAP_X, GAP_Y = 36, 72
MARGIN = 24


@dataclass(frozen=True, slots=True)
class Link:
    """One stored edge between two different files."""

    src_path: str
    dst_path: str
    edge: Edge


@dataclass(slots=True)
class Box:
    name: str            # as shown: "app/" or "server.py"
    path: str            # from the repository root; a folder ends with "/"
    is_folder: bool
    files: int
    tiers: Counter[str] = field(default_factory=Counter)
    x: float = 0.0
    y: float = 0.0

    @property
    def tier(self) -> str:
        """The deepest tier of any file inside: one deep file makes the box worth opening."""
        return next((str(t) for t in Tier if self.tiers[str(t)]), str(Tier.TEXT))


@dataclass(slots=True)
class Arrow:
    src: str
    dst: str
    count: int
    levels: dict[str, int]
    kinds: dict[str, int]
    path: str = ""

    @property
    def level(self) -> str:
        """Drawn at the best level behind it: one certain edge makes the dependency certain."""
        return next(name for name in LEVELS if self.levels[name])

    @property
    def only_names(self) -> bool:
        """True when nothing but text naming a file is behind it; drawn in grey."""
        return set(self.kinds) == {str(EdgeKind.REFERENCES)}

    @property
    def width(self) -> float:
        """1 edge is a hairline, 1,000 edges a thick line; the scale is logarithmic."""
        return round(min(1.2 + math.log2(self.count) * 0.55, 6.0), 2)


def file_links(nodes: Mapping[str, Node], edges: Iterable[Edge]) -> list[Link]:
    """Every arrow-kind edge whose two ends are in different files of the repository.

    An edge to an outside library has no file on its far end, so it is not here.
    """
    links = []
    for edge in edges:
        if edge.kind not in ARROW_KINDS:
            continue
        src, dst = nodes.get(edge.src_id), nodes.get(edge.dst_id)
        if src and dst and src.path and dst.path and src.path != dst.path:
            links.append(Link(src.path, dst.path, edge))
    return links


def normalise_focus(focus: str) -> str:
    """`app`, `/app/` and `app/` all mean the folder `app/`; the root is the empty string."""
    focus = focus.replace("\\", "/").strip("/")
    return f"{focus}/" if focus else ""


def box_path(path: str, focus: str) -> str | None:
    """The box a file falls in when looking at `focus`: its first part below that folder.

    `box_path("app/api/users.py", "app/")` is `"app/api/"`; a file directly in the folder
    is its own box; a file outside the folder has no box.
    """
    if not path.startswith(focus):
        return None
    head, slash, _ = path[len(focus):].partition("/")
    return f"{focus}{head}{slash}"


def build_diagram(
    files: list[FileRecord],
    links: list[Link],
    focus: str = "",
    pick: str = "",
    show_all: bool = False,
) -> dict[str, Any]:
    """Boxes with positions, arrows with paths, and what was left out, for one folder.

    Every box with an arrow is placed using all arrows, so the layout does not move when
    fewer are drawn. `pick` draws only the arrows touching one box; otherwise a crowded
    diagram draws its heaviest arrows unless `show_all`.
    """
    focus = normalise_focus(focus)
    boxes = _boxes(files, focus)
    arrows, outside = _arrows(links, focus)
    connected = {name for arrow in arrows for name in (arrow.src, arrow.dst)}
    shown = _heaviest(connected, arrows)
    hidden_boxes = len(connected) - len(shown)
    arrows = [a for a in arrows if a.src in shown and a.dst in shown]
    rows = _wrap(layered_rows(sorted(shown), {(a.src, a.dst): a.count for a in arrows}))
    width, height = _place(rows, boxes)
    drawn = arrows_to_draw(arrows, len(shown), pick if pick in shown else "", show_all)
    route_arrows(drawn, boxes)
    return {
        "focus": focus,
        "crumbs": crumbs(focus),
        "boxes": [boxes[name] for row in rows for name in row],
        "arrows": sorted(drawn, key=lambda a: a.count),  # heavy arrows drawn last, on top
        "hidden_arrows": len(arrows) - len(drawn),
        "pick": pick if pick in shown else "",
        "show_all": show_all,
        "loose": sorted((b for p, b in boxes.items() if p not in connected),
                        key=lambda b: (not b.is_folder, b.name)),
        "hidden_boxes": hidden_boxes,
        "outside": outside,
        "width": width,
        "height": height,
        "box_w": BOX_W,
        "box_h": BOX_H,
        "exists": bool(boxes),
    }


def _boxes(files: list[FileRecord], focus: str) -> dict[str, Box]:
    boxes: dict[str, Box] = {}
    for record in files:
        path = box_path(record.path, focus)
        if path is None:
            continue
        name = path[len(focus):]
        box = boxes.setdefault(path, Box(name, path, path.endswith("/"), 0))
        box.files += 1
        box.tiers[str(record.tier)] += 1
    return boxes


def _arrows(links: list[Link], focus: str) -> tuple[list[Arrow], int]:
    """One arrow per ordered pair of boxes, and the count of links leaving the folder."""
    found: dict[tuple[str, str], Arrow] = {}
    outside = 0
    for link in links:
        src, dst = box_path(link.src_path, focus), box_path(link.dst_path, focus)
        if src is None and dst is None:
            continue
        if src is None or dst is None:
            outside += 1
            continue
        if src == dst:
            continue
        arrow = found.setdefault(
            (src, dst), Arrow(src, dst, 0, dict.fromkeys(LEVELS, 0), {})
        )
        arrow.count += 1
        arrow.levels[level(link.edge.confidence)] += 1
        kind = str(link.edge.kind)
        arrow.kinds[kind] = arrow.kinds.get(kind, 0) + 1
    return list(found.values()), outside


def _heaviest(connected: set[str], arrows: list[Arrow]) -> set[str]:
    """At most MAX_BOXES boxes, keeping those with the most edges; the rest are counted."""
    if len(connected) <= MAX_BOXES:
        return connected
    weight: Counter[str] = Counter()
    for arrow in arrows:
        weight[arrow.src] += arrow.count
        weight[arrow.dst] += arrow.count
    ranked = sorted(connected, key=lambda name: (-weight[name], name))
    return set(ranked[:MAX_BOXES])


def arrows_to_draw(arrows: list[Arrow], boxes: int, pick: str, show_all: bool) -> list[Arrow]:
    """The arrows worth drawing. Twenty files can have a hundred arrows between them,
    all real and together unreadable, so by default only the heaviest are drawn: three
    for every two boxes. The caller reports how many were left out."""
    if pick:
        return [a for a in arrows if pick in (a.src, a.dst)]
    limit = max(MIN_ARROWS, int(ARROWS_PER_BOX * boxes))
    if show_all or len(arrows) <= limit:
        return arrows
    return sorted(arrows, key=lambda a: (-a.count, a.src, a.dst))[:limit]


def _wrap(rows: list[list[str]]) -> list[list[str]]:
    """Split a row of more than MAX_ROW boxes into several, so the page never scrolls far."""
    return [row[i:i + MAX_ROW] for row in rows for i in range(0, len(row), MAX_ROW)]


def _place(rows: list[list[str]], boxes: Mapping[str, Box]) -> tuple[float, float]:
    """Give each box its x and y, rows centred; returns the drawing's width and height."""
    widest = max((len(row) for row in rows), default=0)
    width = 2 * MARGIN + widest * BOX_W + max(widest - 1, 0) * GAP_X
    for r, row in enumerate(rows):
        row_width = len(row) * BOX_W + (len(row) - 1) * GAP_X
        left = (width - row_width) / 2
        for i, name in enumerate(row):
            boxes[name].x = left + i * (BOX_W + GAP_X)
            boxes[name].y = MARGIN + r * (BOX_H + GAP_Y)
    height = 2 * MARGIN + len(rows) * BOX_H + max(len(rows) - 1, 0) * GAP_Y
    return width, height


def route_arrows(arrows: list[Arrow], boxes: Mapping[str, Box]) -> None:
    """Give every arrow its curve. Each arrow gets its own point on a box's side.

    Without this every arrow would leave and enter at the middle of a side and they
    would lie on top of each other. The points on one side are ordered by where the
    other end is, left to right, so arrows fan out instead of crossing at the box.
    """
    ends: dict[tuple[str, str], list[tuple[float, int, int]]] = {}
    sides: list[tuple[str, str]] = []
    for index, arrow in enumerate(arrows):
        src, dst = boxes[arrow.src], boxes[arrow.dst]
        src_side, dst_side = _sides(src, dst)
        sides.append((src_side, dst_side))
        ends.setdefault((arrow.src, src_side), []).append((dst.x, index, 0))
        ends.setdefault((arrow.dst, dst_side), []).append((src.x, index, 1))
    points: dict[tuple[int, int], tuple[float, float]] = {}
    for (name, side), entries in ends.items():
        box = boxes[name]
        y = box.y if side == "top" else box.y + BOX_H
        for slot, (_, index, end) in enumerate(sorted(entries), start=1):
            points[(index, end)] = (box.x + BOX_W * slot / (len(entries) + 1), y)
    for index, arrow in enumerate(arrows):
        arrow.path = curve(points[(index, 0)], points[(index, 1)], sides[index][0])


def _sides(src: Box, dst: Box) -> tuple[str, str]:
    """The sides an arrow leaves and enters by: the two that face each other."""
    if dst.y > src.y:
        return "bottom", "top"
    if dst.y < src.y:
        return "top", "bottom"
    side = "bottom" if src.x < dst.x else "top"   # same row: arc under one way, over the other
    return side, side


def curve(start: tuple[float, float], end: tuple[float, float], src_side: str) -> str:
    """An SVG cubic curve that leaves and arrives vertically, so arrowheads point straight in."""
    (sx, sy), (ex, ey) = start, end
    if sy == ey:    # same row: both control points pushed away from the boxes
        mid = sy + (GAP_Y * 0.45 if src_side == "bottom" else -GAP_Y * 0.45)
    else:
        mid = (sy + ey) / 2
    return f"M{sx:.0f},{sy:.0f} C{sx:.0f},{mid:.0f} {ex:.0f},{mid:.0f} {ex:.0f},{ey:.0f}"


def crumbs(path: str) -> list[dict[str, str]]:
    """The folders from the root down a path, each with the focus that opens it.

    For a folder (`app/api/`) every part is a folder. For a file (`app/api/users.py`)
    the last part is the file itself, marked with an empty focus.
    """
    parts = path.strip("/").split("/") if path else []
    is_file = bool(path) and not path.endswith("/")
    return [
        {"name": part,
         "focus": "" if is_file and i == len(parts) - 1 else "/".join(parts[:i + 1]) + "/"}
        for i, part in enumerate(parts)
    ]


def arrow_edges(
    links: list[Link], nodes: Mapping[str, Node], focus: str, src: str, dst: str
) -> dict[str, Any]:
    """The stored edges behind one arrow, strongest first: the proof the arrow is real."""
    focus = normalise_focus(focus)
    behind = [
        link for link in links
        if box_path(link.src_path, focus) == src and box_path(link.dst_path, focus) == dst
    ]
    behind.sort(key=lambda k: (-k.edge.confidence, k.src_path, k.edge.line or 0))
    rows = [
        {
            "src": nodes[link.edge.src_id],
            "dst": nodes[link.edge.dst_id],
            "kind": str(link.edge.kind),
            "resolution": str(link.edge.resolution),
            "confidence": link.edge.confidence,
            "level": level(link.edge.confidence),
            "line": link.edge.line,
        }
        for link in behind[:MAX_ARROW_EDGES]
    ]
    return {"src": src, "dst": dst, "total": len(behind), "rows": rows}
