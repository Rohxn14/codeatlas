"""The impact engine on a hand-built snapshot: each signal alone, then combined."""

from __future__ import annotations

import pytest

from codeatlas.impact import Change, ImpactConfig, impact, parse_diff
from codeatlas.models import EdgeKind, NodeKind, Resolution, make_node_id
from tests.impact.impact_graph import SNAP, _edge, _node, build_store

SAVE = Change("app/repo.py", ((3, 3),))


@pytest.fixture
def store():
    s = build_store()
    yield s
    s.close()


def scores(result):
    return {t.key: t.score for t in result.targets}


def test_graph_signal_scores_confidence_times_decay_per_hop(store):
    got = scores(impact(store, SNAP, [SAVE]))
    assert got["app/service.py::create"] == pytest.approx(0.9 * 0.8)
    assert got["app/api.py::handler"] == pytest.approx(0.9 * 0.8 * 1.0 * 0.8)
    assert got["app/service.py::rename"] == pytest.approx(0.9 * 0.8 * 0.5 * 0.8)


def test_graph_evidence_is_the_best_path_with_edge_kinds(store):
    result = impact(store, SNAP, [SAVE])
    handler = next(t for t in result.targets if t.key == "app/api.py::handler")
    path = handler.evidence[0].path
    assert [h.key for h in path] == [
        "app/repo.py::Repo.save", "app/service.py::create", "app/api.py::handler"]
    assert [(h.kind, h.confidence) for h in path[1:]] == [("calls", 0.9), ("calls", 1.0)]


def test_depth_limits_the_walk(store):
    got = scores(impact(store, SNAP, [SAVE], ImpactConfig(depth=1)))
    assert "app/service.py::create" in got
    assert "app/api.py::handler" not in got


def test_owner_class_importers_are_reached(store):
    got = scores(impact(store, SNAP, [SAVE]))
    assert got["app/repo.py::Repo"] == pytest.approx(0.8)
    assert got["app/service.py::"] == pytest.approx(0.64)  # imports Repo: 1.0 * 0.8 * 0.8


def test_import_signal_alone(store):
    result = impact(store, SNAP, [SAVE])
    other = next(t for t in result.targets if t.key == "app/other.py::")
    assert [e.signal for e in other.evidence] == ["import"]
    assert other.score == pytest.approx(1.0 * 0.8 * 0.5)
    assert "imports app/repo.py::" in other.evidence[0].detail


def test_cochange_signal_alone_carries_its_support(store):
    result = impact(store, SNAP, [SAVE])
    settings = next(t for t in result.targets if t.key == "app/settings.py::")
    assert [e.signal for e in settings.evidence] == ["cochange"]
    assert settings.score == pytest.approx(0.6 * 0.7)
    assert "3 of 5 commits" in settings.evidence[0].detail


def test_tests_signal_alone(store):
    result = impact(store, SNAP, [SAVE])
    pick = next(t for t in result.tests if t.key == "tests/test_repo.py::test_save")
    assert [e.signal for e in pick.evidence] == ["tests"]
    assert pick.score == pytest.approx(1.0 * 1.0 * 0.9)


def test_convention_edge_selects_the_test_module(store):
    result = impact(store, SNAP, [Change("app/util.py", ((1, 3),))])
    pick = next(t for t in result.tests if t.key == "tests/test_util.py::")
    assert pick.kind == "module"
    assert pick.score == pytest.approx(0.8 * 0.9)


def test_tests_are_found_through_calls_and_through_tests_edges(store):
    result = impact(store, SNAP, [SAVE])
    picked = {t.key: t.score for t in result.tests}
    assert picked["tests/test_service.py::test_create"] == pytest.approx(0.9 * 0.8 * 0.8)
    assert picked["tests/test_repo.py::test_save"] == pytest.approx(0.9)
    assert [t.path for t in result.test_files()] == [
        "tests/test_repo.py", "tests/test_service.py"]


def test_max_takes_the_highest_signal_and_noisy_or_lets_signals_agree(store):
    api = "app/api.py::"
    best = scores(impact(store, SNAP, [SAVE]))[api]
    assert best == pytest.approx(0.576)  # graph 0.576 beats co-change 0.5 * 0.7
    both = scores(impact(store, SNAP, [SAVE], ImpactConfig(combine="noisy_or")))[api]
    assert both == pytest.approx(1 - (1 - 0.576) * (1 - 0.35))


def test_a_diff_touching_two_functions_and_a_readme(store):
    diff = (
        "diff --git a/app/service.py b/app/service.py\n"
        "--- a/app/service.py\n+++ b/app/service.py\n"
        "@@ -3,1 +3,2 @@ def create\n@@ -8,1 +9,1 @@ def rename\n"
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n"
    )
    result = impact(store, SNAP, parse_diff(diff))
    assert result.changed == (
        "app/service.py::create", "app/service.py::rename", "README.md::")
    assert any("README.md has no symbols" in w for w in result.warnings)
    # create changed: its callers and test are reached
    assert "app/api.py::handler" in scores(result)


def test_a_file_outside_the_snapshot_is_a_warning_not_an_error(store):
    result = impact(store, SNAP, [Change("app/brand_new.py", ((1, 2),)), SAVE])
    assert any("app/brand_new.py is not in the snapshot" in w for w in result.warnings)
    assert result.changed == ("app/repo.py::Repo.save",)


def test_lines_outside_any_symbol_map_to_the_module(store):
    result = impact(store, SNAP, [Change("app/service.py", ((1, 1),))])
    assert result.changed == ("app/service.py::",)


def test_a_range_over_two_functions_maps_to_both_and_the_gap_between(store):
    result = impact(store, SNAP, [Change("app/service.py", ((4, 8),))])
    # line 6 lies between create (3-5) and rename (7-9): top-level code
    assert result.changed == (
        "app/service.py::create", "app/service.py::", "app/service.py::rename")


def test_a_range_inside_one_symbol_maps_only_to_it(store):
    result = impact(store, SNAP, [Change("app/service.py", ((3, 5),))])
    assert result.changed == ("app/service.py::create",)


def test_a_range_from_the_imports_into_a_symbol_keeps_the_module(store):
    result = impact(store, SNAP, [Change("app/service.py", ((1, 5),))])
    assert set(result.changed) == {"app/service.py::", "app/service.py::create"}


def test_a_file_without_ranges_maps_to_the_module_and_every_symbol(store):
    result = impact(store, SNAP, [Change("app/service.py")])
    assert set(result.changed) == {
        "app/service.py::", "app/service.py::create", "app/service.py::rename"}


def test_a_changed_test_is_always_selected(store):
    result = impact(store, SNAP, [Change("tests/test_repo.py", ((3, 4),))])
    picked = {t.key: t.score for t in result.tests}
    assert picked["tests/test_repo.py::test_save"] == 1.0
    assert picked["tests/test_repo.py::"] == 1.0


def test_symbol_keys_are_mapped_directly(store):
    result = impact(store, SNAP, [Change("app/repo.py", symbol_keys=("app/repo.py::Repo.save",))])
    assert result.changed == ("app/repo.py::Repo.save",)
    missing = impact(store, SNAP, [Change("x.py", symbol_keys=("x.py::nope",))])
    assert missing.warnings == ("symbol x.py::nope is not in the snapshot",)


def test_min_score_drops_weak_targets(store):
    got = scores(impact(store, SNAP, [SAVE], ImpactConfig(min_score=0.5)))
    assert "app/service.py::rename" not in got
    assert "app/service.py::create" in got


def test_decay_must_be_strictly_between_zero_and_one():
    for bad in (0.0, 1.0, 1.5, -0.1):
        with pytest.raises(ValueError, match="decay"):
            ImpactConfig(decay=bad)


def test_a_changed_handler_reaches_its_route_and_the_http_client(store):
    route = "http::GET /users"
    store.write_nodes([
        _node(route, NodeKind.ROUTE, 0, 0, language="http"),
        _node("web/client.ts::", NodeKind.MODULE, 1, 5, language="typescript"),
        _node("web/client.ts::fetchUsers", NodeKind.FUNCTION, 2, 4, language="typescript"),
    ])
    store.write_edges(SNAP, [
        _edge(route, "app/api.py::handler", EdgeKind.HANDLES, 1.0, Resolution.DIRECT),
        _edge("web/client.ts::fetchUsers", route, EdgeKind.CALLS_HTTP, 0.9,
              Resolution.ROUTE_EXACT),
    ])
    result = impact(store, SNAP, [Change("app/api.py", ((4, 4),))])
    got = scores(result)
    assert got[route] == pytest.approx(1.0 * 0.8)
    assert got["web/client.ts::fetchUsers"] == pytest.approx(1.0 * 0.8 * 0.9 * 0.8)
    client = next(t for t in result.targets if t.key == "web/client.ts::fetchUsers")
    assert [(h.key, h.kind) for h in client.evidence[0].path] == [
        ("app/api.py::handler", None), (route, "handles"),
        ("web/client.ts::fetchUsers", "calls_http")]


def test_trace_stops_on_a_cycle_of_equal_scores(store):
    from codeatlas.impact import ImpactEngine

    engine = ImpactEngine(store, SNAP)
    a, b = (make_node_id(SNAP, k) for k in ("app/util.py::", "app/other.py::"))
    engine._walk.add_edge(a, b, kind="calls", raw=1.0, confidence=1.0)
    engine._walk.add_edge(b, a, kind="calls", raw=1.0, confidence=1.0)
    hops = engine._trace(a, {"never"}, {a: 0.5, b: 0.5})
    assert len(hops) <= 3
