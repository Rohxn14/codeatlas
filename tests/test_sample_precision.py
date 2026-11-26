"""The arithmetic behind the precision measurement: the interval and the weighting."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "sample_precision.py"
spec = importlib.util.spec_from_file_location("sample_precision", SCRIPT)
assert spec and spec.loader
sample_precision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sample_precision)


def test_the_interval_is_wide_for_twenty_rows_and_never_leaves_zero_to_one() -> None:
    lo, hi = sample_precision.wilson(6, 20)
    assert lo == pytest.approx(0.145, abs=0.001) and hi == pytest.approx(0.519, abs=0.001)
    assert sample_precision.wilson(20, 20)[1] == 1.0  # all right still has a lower bound
    assert sample_precision.wilson(20, 20)[0] == pytest.approx(0.839, abs=0.001)
    assert sample_precision.wilson(0, 5)[0] == 0.0


def test_the_share_of_all_edges_is_weighted_by_each_stratum_s_size() -> None:
    rows = ([{"stratum": "direct", "confidence": 1.0, "right": True}] * 2
            + [{"stratum": "name_guess", "confidence": 0.2, "right": r} for r in (True, False)])
    table = sample_precision.score(rows, {"direct": 300, "name_guess": 100})
    assert "| direct | 2/2 | 1.00 |" in table and "| name_guess | 1/2 | 0.50 |" in table
    assert "about 88% of all CALLS edges" in table  # (300 * 1.0 + 100 * 0.5) / 400
