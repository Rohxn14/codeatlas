"""The architecture diagram: the layout steps, boxes and arrows, and the map page."""

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.config import Config
from codeatlas.indexer.pipeline import index_repository
from codeatlas.models import Edge, EdgeKind, FileRecord, Node, NodeKind, Resolution, Span, Tier
from codeatlas.web import create_app, snapshot_slug
from codeatlas.web.diagram import (
    Arrow,
    Link,
    arrow_edges,
    arrows_to_draw,
    box_path,
    build_diagram,
    crumbs,
    file_links,
    normalise_focus,
)
from codeatlas.web.layout import acyclic_pairs, assign_layers, layered_rows, order_rows

# Layout


def test_heavier_arrow_wins_a_two_way_pair() -> None:
    kept = acyclic_pairs(["a", "b"], {("a", "b"): 10, ("b", "a"): 2})
    assert kept == {("a", "b")}


def test_arrow_that_would_close_a_longer_cycle_is_skipped() -> None:
    weights = {("a", "b"): 5, ("b", "c"): 4, ("c", "a"): 1}
    assert acyclic_pairs("abc", weights) == {("a", "b"), ("b", "c")}


def test_self_arrows_and_unknown_names_are_ignored() -> None:
    assert acyclic_pairs(["a"], {("a", "a"): 3, ("a", "zzz"): 3}) == set()


def test_layers_put_users_above_what_they_use() -> None:
    layers = assign_layers("abcd", {("a", "b"), ("b", "c"), ("a", "c")})
    assert layers == {"a": 0, "b": 1, "c": 2, "d": 0}  # c sits below its lowest user, b


def test_rows_are_ordered_to_sit_under_their_neighbours() -> None:
    # a uses d and b uses c. Sorted by name the arrows would cross (a over c, b over d).
    pairs = {("a", "d"), ("b", "c")}
    top, bottom = order_rows({"a": 0, "b": 0, "c": 1, "d": 1}, pairs)
    assert top.index("a") == bottom.index("d")
    assert top.index("b") == bottom.index("c")


def test_layout_is_the_same_on_every_run() -> None:
    weights = {("x", "y"): 1, ("y", "z"): 1, ("z", "x"): 1, ("w", "z"): 2}
    assert layered_rows("wxyz", weights) == layered_rows("zyxw", weights)


def test_layout_of_nothing_is_empty() -> None:
    assert layered_rows([], {}) == []


# Boxes and arrows


def record(path: str, tier: Tier = Tier.DEEP) -> FileRecord:
    return FileRecord(path, "python", tier, "x", 1)


def node(path: str, name: str = "f") -> Node:
    key = f"{path}::{name}"
    return Node(f"s/{key}", key, "s", NodeKind.FUNCTION, "python", name, name, path, Span(1, 2))


def link(src: str, dst: str, confidence: float = 1.0, kind: EdgeKind = EdgeKind.CALLS) -> Link:
    edge = Edge(node(src).id, node(dst).id, kind, confidence, Resolution.DIRECT, line=3)
    return Link(src, dst, edge)


FILES = [record("app/api/users.py"), record("app/db.py"), record("lib/util.py"),
         record("README.md", Tier.TEXT)]


@pytest.mark.parametrize(
    ("path", "focus", "expected"),
    [
        ("app/api/users.py", "", "app/"),
        ("app/api/users.py", "app/", "app/api/"),
        ("app/db.py", "app/", "app/db.py"),
        ("README.md", "", "README.md"),
        ("lib/util.py", "app/", None),
        ("application/x.py", "app/", None),   # a folder whose name only starts the same
    ],
)
def test_box_path(path: str, focus: str, expected: str | None) -> None:
    assert box_path(path, focus) == expected


def test_focus_spellings_mean_the_same_folder() -> None:
    assert normalise_focus("app") == normalise_focus("/app/") == normalise_focus("app\\") == "app/"
    assert normalise_focus("") == normalise_focus("/") == ""
    assert crumbs("app/api/") == [
        {"name": "app", "focus": "app/"}, {"name": "api", "focus": "app/api/"},
    ]


def test_file_links_keep_only_edges_between_two_files() -> None:
    a, b, outside = node("a.py"), node("b.py"), node("", "requests")
    nodes = {n.id: n for n in (a, b, outside)}
    edges = [
        Edge(a.id, b.id, EdgeKind.CALLS, 1.0, Resolution.DIRECT),
        Edge(a.id, a.id, EdgeKind.CALLS, 1.0, Resolution.DIRECT),          # same file
        Edge(a.id, outside.id, EdgeKind.CALLS, 1.0, Resolution.DIRECT),    # outside library
        Edge(a.id, b.id, EdgeKind.CO_CHANGES, 0.5, Resolution.HISTORY),    # not a "uses" kind
        Edge(a.id, "s/gone", EdgeKind.CALLS, 1.0, Resolution.DIRECT),      # unknown end
    ]
    assert [(k.src_path, k.dst_path) for k in file_links(nodes, edges)] == [("a.py", "b.py")]


def test_arrows_are_counted_per_pair_of_boxes() -> None:
    links = [link("app/api/users.py", "lib/util.py"),
             link("app/db.py", "lib/util.py", 0.2),
             link("app/api/users.py", "app/db.py")]            # inside app/: no arrow at the root
    diagram = build_diagram(FILES, links)
    (arrow,) = diagram["arrows"]
    assert (arrow.src, arrow.dst, arrow.count) == ("app/", "lib/", 2)
    assert arrow.levels == {"certain": 1, "likely": 0, "guess": 1}
    assert arrow.level == "certain"            # one certain edge is enough
    assert arrow.path.startswith("M")
    assert [b.path for b in diagram["boxes"]] == ["app/", "lib/"]
    assert [b.path for b in diagram["loose"]] == ["README.md"]
    assert diagram["outside"] == 0


def test_an_arrow_of_guesses_only_is_a_guess() -> None:
    diagram = build_diagram(FILES, [link("app/db.py", "lib/util.py", 0.2)])
    assert diagram["arrows"][0].level == "guess"


def test_inside_a_folder_links_that_leave_it_are_counted_not_drawn() -> None:
    links = [link("app/api/users.py", "app/db.py"), link("app/db.py", "lib/util.py")]
    diagram = build_diagram(FILES, links, focus="app")
    assert [(a.src, a.dst) for a in diagram["arrows"]] == [("app/api/", "app/db.py")]
    assert diagram["outside"] == 1
    assert diagram["focus"] == "app/"


def test_a_folder_that_does_not_exist_has_no_boxes() -> None:
    assert build_diagram(FILES, [], focus="nope")["exists"] is False


def test_both_directions_get_separate_curves() -> None:
    links = [link("app/db.py", "lib/util.py"), link("lib/util.py", "app/db.py")]
    one, two = build_diagram(FILES, links)["arrows"]
    assert one.path != two.path


def arrow(src: str, dst: str, count: int) -> Arrow:
    return Arrow(src, dst, count, {"certain": count, "likely": 0, "guess": 0}, {})


def test_a_crowded_diagram_draws_its_heaviest_arrows() -> None:
    arrows = [arrow("a", f"b{i}", i + 1) for i in range(20)]
    drawn = arrows_to_draw(arrows, boxes=4, pick="", show_all=False)
    assert len(drawn) == 12
    assert min(a.count for a in drawn) == 9
    assert arrows_to_draw(arrows, boxes=4, pick="", show_all=True) == arrows


def test_picking_a_box_draws_only_its_arrows() -> None:
    arrows = [arrow("a", "b", 1), arrow("b", "c", 1), arrow("c", "d", 1)]
    drawn = arrows_to_draw(arrows, boxes=4, pick="b", show_all=False)
    assert [(a.src, a.dst) for a in drawn] == [("a", "b"), ("b", "c")]


def test_arrow_edges_lists_what_is_behind_an_arrow_surest_first() -> None:
    links = [link("app/db.py", "lib/util.py", 0.2), link("app/api/users.py", "lib/util.py"),
             link("lib/util.py", "app/db.py")]
    nodes = {n.id: n for n in (node("app/db.py"), node("app/api/users.py"), node("lib/util.py"))}
    behind = arrow_edges(links, nodes, "", "app/", "lib/")
    assert behind["total"] == 2
    assert [row["confidence"] for row in behind["rows"]] == [1.0, 0.2]
    assert [row["level"] for row in behind["rows"]] == ["certain", "guess"]
    assert behind["rows"][0]["src"].path == "app/api/users.py"


# The page

REPO = {
    "app/service.py": "from lib.util import helper\n\ndef save():\n    helper()\n",
    "lib/util.py": "def helper():\n    pass\n",
    "notes.txt": "hello\n",
}


@pytest.fixture
def client(make_repo: Callable[..., Path], tmp_path: Path) -> tuple[TestClient, str]:
    config = Config(data_dir=(tmp_path / "data").as_posix())
    db_path = tmp_path / "data" / "codeatlas.db"
    report = index_repository(str(make_repo(REPO, name="demo")), config, db_path)
    return TestClient(create_app(db_path, config)), f"/s/{snapshot_slug(report.snapshot['id'])}/"


def test_map_page_draws_boxes_and_an_arrow(client: tuple[TestClient, str]) -> None:
    http, address = client
    page = http.get(address)
    assert page.status_code == 200
    assert "<svg" in page.text
    assert "app/ uses lib/" in page.text           # the arrow's tooltip
    assert "notes.txt" in page.text                # listed as not connected
    nav = page.text.split('<nav aria-label="Repository">')[1].split("</nav>")[0]
    assert nav.count('aria-current="page"') == 1  # and it is the map
    assert "Map" in nav.split('aria-current="page"')[1].split("</a>")[0]


def test_clicking_an_arrow_lists_its_edges(client: tuple[TestClient, str]) -> None:
    http, address = client
    page = http.get(address, params={"src": "app/", "dst": "lib/"})
    assert page.status_code == 200
    assert 'id="arrow"' in page.text
    assert "app/service.py" in page.text and "helper" in page.text


def test_an_arrow_that_does_not_exist_says_so(client: tuple[TestClient, str]) -> None:
    http, address = client
    page = http.get(address, params={"src": "lib/", "dst": "nowhere/"})
    assert page.status_code == 200
    assert "No edge goes from" in page.text


def test_opening_a_folder_and_an_unknown_folder(client: tuple[TestClient, str]) -> None:
    http, address = client
    inside = http.get(address, params={"focus": "app/"})
    assert inside.status_code == 200
    assert "service.py" in inside.text
    assert "connect this folder to the rest" in inside.text
    assert http.get(address, params={"focus": "nope/"}).status_code == 404


def test_an_arrow_of_names_only_is_marked(tmp_path: Path) -> None:
    from codeatlas.web.diagram import Arrow

    levels = {"certain": 1, "likely": 0, "guess": 0}
    assert Arrow("README.md", "images/", 1, levels, {"references": 1}).only_names
    assert not Arrow("a/", "b/", 2, levels, {"references": 1, "calls": 1}).only_names
