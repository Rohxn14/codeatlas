import networkx as nx
import pytest

from codeatlas.models import EdgeKind
from codeatlas.store.graph import callees, callers, reverse_reach


def calls(g: nx.MultiDiGraph, src: str, dst: str, confidence: float) -> None:
    g.add_edge(src, dst, kind=EdgeKind.CALLS, confidence=confidence, resolution="x", line=1)


@pytest.fixture
def two_paths() -> nx.MultiDiGraph:
    """`a` reaches `d` two ways: a -> b -> d (0.9 x 0.9) and a -> c -> d (1.0 x 0.5)."""
    g = nx.MultiDiGraph()
    calls(g, "a", "b", 0.9)
    calls(g, "b", "d", 0.9)
    calls(g, "a", "c", 1.0)
    calls(g, "c", "d", 0.5)
    g.add_edge("m", "a", kind=EdgeKind.CONTAINS, confidence=1.0, resolution="x", line=None)
    return g


def test_reverse_reach_keeps_best_path_confidence(two_paths: nx.MultiDiGraph) -> None:
    reach = reverse_reach(two_paths, ["d"], kinds=[EdgeKind.CALLS])
    assert reach == pytest.approx({"b": 0.9, "c": 0.5, "a": 0.81})


def test_reverse_reach_follows_all_kinds_by_default(two_paths: nx.MultiDiGraph) -> None:
    assert reverse_reach(two_paths, ["d"])["m"] == pytest.approx(0.81)


def test_reverse_reach_depth_limits_path_length() -> None:
    # The best path to d is three edges long; within two edges only the weak one counts.
    g = nx.MultiDiGraph()
    calls(g, "a", "b", 1.0)
    calls(g, "b", "c", 1.0)
    calls(g, "c", "d", 1.0)
    calls(g, "a", "d", 0.2)
    assert reverse_reach(g, ["d"], depth=2) == pytest.approx({"c": 1.0, "b": 1.0, "a": 0.2})
    assert reverse_reach(g, ["d"], depth=3)["a"] == pytest.approx(1.0)


def test_reverse_reach_terminates_on_cycles_and_skips_starts() -> None:
    g = nx.MultiDiGraph()
    calls(g, "a", "b", 0.5)
    calls(g, "b", "a", 0.5)
    assert reverse_reach(g, ["a"]) == {"b": 0.5}
    assert reverse_reach(g, ["missing"]) == {}


def test_callers_and_callees(two_paths: nx.MultiDiGraph) -> None:
    assert callers(two_paths, "d") == pytest.approx({"b": 0.9, "c": 0.5})
    assert callers(two_paths, "d", depth=2, min_confidence=0.6) == pytest.approx(
        {"b": 0.9, "a": 0.81}
    )
    assert callees(two_paths, "a", depth=2) == pytest.approx(
        {"b": 0.9, "c": 1.0, "d": 0.81}
    )
    # CONTAINS edges are not calls.
    assert callers(two_paths, "a") == {}


def test_depth_limit_uses_scores_from_the_start_of_each_round() -> None:
    """At depth 2, `a` reaches `d` only through y -> d (0.5); a -> y -> x -> d is 3 edges.

    In round 2, `x` (processed first, as it sorts first) improves `y` to 0.9. If `y`
    then extended `a` with that new score, `a` would get 0.9 from a three-edge path.
    """
    g = nx.MultiDiGraph()
    calls(g, "y", "d", 0.5)
    calls(g, "x", "d", 0.9)
    calls(g, "y", "x", 1.0)
    calls(g, "a", "y", 1.0)
    assert reverse_reach(g, ["d"], depth=2)["a"] == pytest.approx(0.5)
    assert reverse_reach(g, ["d"])["a"] == pytest.approx(0.9)
