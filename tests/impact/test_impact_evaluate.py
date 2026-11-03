"""The evaluation's metrics on hand-made truth over the small snapshot."""

from __future__ import annotations

import pytest

from codeatlas.impact import Change, ImpactEngine
from codeatlas.impact.evaluate import (
    Mutant,
    all_test_files,
    change_for,
    default_selectors,
    evaluate_mutants,
    f1_by_threshold,
    leave_one_out,
    lobo_table,
    mutants_from_truth,
    prf,
    table,
)
from tests.impact.impact_graph import SNAP, build_store


@pytest.fixture
def engine():
    store = build_store()
    yield ImpactEngine(store, SNAP)
    store.close()


def test_prf_counts_hits():
    got = prf(["a", "b", "c"], frozenset({"a", "b", "d", "e"}))
    assert (got.precision, got.recall) == (pytest.approx(2 / 3), 0.5)
    assert got.f1 == pytest.approx(2 * (2 / 3) * 0.5 / (2 / 3 + 0.5))


def test_prf_of_an_empty_selection_is_zero_not_an_error():
    got = prf([], frozenset({"a"}))
    assert (got.precision, got.recall, got.f1) == (0.0, 0.0, 0.0)


def test_truth_ids_become_files():
    truth = {"mutants": [
        {"function": "f", "status": "mutated",
         "failing_tests": ["t/a.py::test_x[1]", "t/a.py::test_y", "t/b.py::C::test_z"]},
        {"function": "g", "status": "skipped"},
    ]}
    first, second = mutants_from_truth(truth)
    assert first.failing_files == {"t/a.py", "t/b.py"}
    assert second.status == "skipped" and not second.failing_files


def test_support_files_are_not_in_the_test_universe(engine):
    assert all_test_files(engine) == {
        "tests/test_service.py", "tests/test_repo.py", "tests/test_util.py"}


def test_mutant_change_is_the_functions_span(engine):
    assert change_for(engine, "app/service.py::create") == Change("app/service.py", ((3, 5),))
    assert change_for(engine, "app/nope.py::f") is None


def test_scores_on_hand_made_truth(engine):
    mutants = [
        Mutant("app/service.py::create", frozenset({"tests/test_service.py"})),
        Mutant("app/repo.py::Repo.save",
               frozenset({"tests/test_repo.py", "tests/test_service.py"})),
        Mutant("app/api.py::handler", frozenset()),  # no test notices: reported apart
        Mutant("app/util.py::", frozenset({"x"}), status="skipped"),
    ]
    result = evaluate_mutants(engine, mutants, default_selectors())
    engine_scores = result["scores"]["engine"]
    assert (engine_scores["precision"], engine_scores["recall"], engine_scores["f1"]) == (
        1.0, 1.0, 1.0)
    assert engine_scores["skipped_share"] == pytest.approx((2 / 3 + 1 / 3) / 2, abs=1e-4)
    run_all = result["scores"]["run-all"]
    assert run_all["recall"] == 1.0 and run_all["precision"] == pytest.approx(0.5, abs=1e-4)
    assert result["scores"]["engine"]["mutants"] == 2
    assert result["caught_by_no_test"] == ["app/api.py::handler"]
    assert result["skipped_mutants"] == ["app/util.py::"]


def test_importing_tests_baseline_misses_tests_that_only_call(engine):
    mutants = [Mutant("app/repo.py::Repo.save", frozenset({"tests/test_repo.py"}))]
    result = evaluate_mutants(engine, mutants, default_selectors())
    # test_repo.py reaches Repo.save through a TESTS edge, not an import
    assert result["scores"]["importing-tests"]["recall"] == 0.0
    assert result["scores"]["engine"]["recall"] == 1.0


def test_truth_names_relative_to_a_folder_are_matched_by_suffix(engine):
    mutants = [Mutant("app/service.py::create", frozenset({"test_service.py"}))]
    result = evaluate_mutants(engine, mutants, default_selectors())
    assert result["scores"]["engine"]["recall"] == 1.0


def test_table_renders_every_selector(engine):
    result = evaluate_mutants(
        engine, [Mutant("app/service.py::create", frozenset({"tests/test_service.py"}))],
        default_selectors())
    text = table("demo", result)
    assert text.startswith("### demo")
    for name in ("engine", "run-all", "importing-tests", "cochange-only"):
        assert f"| {name} |" in text


def test_threshold_sweep_matches_the_natural_cut_off(engine):
    mutants = [Mutant("app/service.py::create", frozenset({"tests/test_service.py"}))]
    sweep = f1_by_threshold(engine, mutants, (0.3, 0.99))
    assert sweep == {0.3: 1.0, 0.99: 0.0}  # the test file scores 0.8: one hop of decay


def test_leave_one_out_tunes_on_the_other_benchmarks_only():
    sweeps = {"a": {0.2: 0.9, 0.5: 0.1}, "b": {0.2: 0.2, 0.5: 0.6}}
    rows = {r["held_out"]: r for r in leave_one_out(sweeps, default=0.5)}
    assert rows["a"]["tuned_on_others"] == 0.5 and rows["a"]["f1_tuned"] == 0.1
    assert rows["a"]["oracle"] == 0.2 and rows["a"]["f1_default"] == 0.1
    assert rows["b"]["tuned_on_others"] == 0.2 and rows["b"]["f1_tuned"] == 0.2
    assert "| a | 0.5 | 0.1 |" in lobo_table(list(rows.values()))


def test_leave_one_out_needs_two_benchmarks():
    assert leave_one_out({"a": {0.3: 1.0}}, default=0.3) == []
