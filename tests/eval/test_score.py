"""The scorer on tiny hand-made graphs whose answers are worked out by hand."""

import json

import pytest

from eval.oracle import score
from eval.oracle.graph import GraphEdge, parse_graph


def node(key, language="python", kind="function"):
    return {"key": key, "kind": kind, "language": language, "path": key.split("::")[0]}


def edge(src, dst, kind="calls", confidence=1.0, resolution="direct", line=1):
    return {"src_key": src, "dst_key": dst, "kind": kind, "confidence": confidence,
            "resolution": resolution, "line": line}


TRUTH = {
    "nodes": [node("a.py::f"), node("a.py::g"), node("a.py::h"), node("a.py::"),
              node("b.ts::run", "typescript"), node("b.ts::stop", "typescript")],
    "edges": [
        edge("a.py::f", "a.py::g", line=2),
        edge("a.py::f", "a.py::h", line=3),
        edge("a.py::g", "a.py::h", line=6),
        edge("b.ts::run", "b.ts::stop", line=4),
        edge("a.py::", "a.py::f", kind="contains"),
    ],
    "unresolvable": [{"src_key": "a.py::h", "line": 9, "callee_text": "table[k]"}],
}

PREDICTED = {
    "nodes": [],
    "edges": [
        edge("a.py::f", "a.py::g", resolution="direct", confidence=1.0),       # TP
        edge("a.py::f", "a.py::g", resolution="name_guess", confidence=0.2),   # duplicate
        edge("a.py::f", "a.py::h", resolution="import_scoped", confidence=0.5),  # TP
        edge("a.py::g", "a.py::f", resolution="name_guess", confidence=0.25),  # FP
        edge("b.ts::run", "b.ts::run", resolution="self_method", confidence=0.9),  # FP
        edge("a.py::h", "a.py::g", resolution="name_guess", confidence=0.1, line=9),  # dynamic
        edge("a.py::f", "requests::get", resolution="direct"),  # endpoint outside truth
        edge("a.py::", "a.py::f", kind="imports"),  # kind the truth does not label
        edge("a.py::", "a.py::f", kind="contains", resolution="structural"),  # TP
    ],
}


@pytest.fixture
def result():
    return score.score(parse_graph(PREDICTED), parse_graph(TRUTH))


def test_overall_and_per_kind(result):
    # Scored: 4 calls (2 TP, 2 FP) + 1 contains (TP). Truth: 5 edges, 3 found.
    assert result["overall"] == {"tp": 3, "fp": 2, "fn": 2, "precision": 0.6, "recall": 0.6,
                                 "f1": pytest.approx(0.6)}
    calls = result["by_kind"]["calls"]
    assert (calls["tp"], calls["fp"], calls["fn"]) == (2, 2, 2)
    assert calls["precision"] == 0.5 and calls["recall"] == 0.5
    assert result["by_kind"]["contains"]["f1"] == 1.0


def test_per_language(result):
    python = result["by_language"]["python"]
    assert (python["tp"], python["fp"], python["fn"]) == (3, 1, 1)
    ts = result["by_language"]["typescript"]
    assert (ts["tp"], ts["fp"], ts["fn"], ts["precision"]) == (0, 1, 1, 0.0)
    assert ts["f1"] is None  # precision and recall are both zero


def test_per_resolution(result):
    rows = result["by_resolution"]
    assert rows["direct"]["precision"] == 1.0
    assert rows["direct"]["recall_share"] == 0.25  # 1 of 4 truth calls
    assert rows["name_guess"] == {"tp": 0, "fp": 1, "precision": 0.0, "recall_share": 0.0}
    assert rows["structural"]["recall_share"] == 1.0
    assert "self_method" in rows and rows["self_method"]["fp"] == 1


def test_not_scored_buckets(result):
    skipped = result["not_scored"]
    assert skipped["kind_not_in_truth"] == {"imports": 1}
    assert skipped["endpoint_not_in_truth"] == {"calls": 1}
    (guess,) = skipped["guesses_on_unresolvable_calls"]
    assert (guess["src_key"], guess["line"]) == ("a.py::h", 9)


def test_dedupe_keeps_the_most_confident_copy():
    kept = score.dedupe([
        GraphEdge("a", "b", "calls", 0.2, "name_guess", 3),
        GraphEdge("a", "b", "calls", 1.0, "direct", 5),
        GraphEdge("a", "b", "calls", 1.0, "direct", 4),
    ])
    assert kept == [GraphEdge("a", "b", "calls", 1.0, "direct", 4)]


def test_calibration_bins():
    truth = [GraphEdge("a", str(i), "calls") for i in range(4)]
    predicted = [
        GraphEdge("a", "0", "calls", 0.1), GraphEdge("a", "x", "calls", 0.29),  # bin 1: 1 of 2
        GraphEdge("a", "1", "calls", 0.3),                                     # bin 2 lower edge
        GraphEdge("a", "y", "calls", 0.6),                                     # bin 3
        GraphEdge("a", "2", "calls", 0.9), GraphEdge("a", "3", "calls", 1.0),  # bin 4, closed
        GraphEdge("a", "0", "imports", 0.1),                                   # not a call
    ]
    rows = score.calibration(predicted, truth)
    assert [(r["bin"], r["count"], r["true"]) for r in rows] == [
        ("0.0-0.3", 2, 1), ("0.3-0.6", 1, 1), ("0.6-0.9", 1, 0), ("0.9-1.0", 2, 2),
    ]
    assert rows[0]["share_true"] == 0.5
    assert rows[0]["mean_confidence"] == pytest.approx(0.195)
    assert score.calibration([], truth)[0]["share_true"] is None


def test_worst_lists_put_confident_mistakes_first(result):
    fps = result["worst_false_positives"]
    assert [e["resolution"] for e in fps] == ["self_method", "name_guess"]
    assert fps[0]["file"] == "b.ts"
    fns = result["worst_false_negatives"]
    assert [(e["src_key"], e["dst_key"], e["line"]) for e in fns] == [
        ("a.py::g", "a.py::h", 6), ("b.ts::run", "b.ts::stop", 4),
    ]


def test_worst_is_capped():
    truth = [GraphEdge("a", str(i), "calls", line=i) for i in range(30)]
    fps, fns = score.worst([], truth)
    assert fps == [] and len(fns) == score.WORST


def test_main_prints_and_saves_a_timestamped_result(tmp_path, capsys):
    predicted, truth = tmp_path / "pred.json", tmp_path / "expected_graph.json"
    predicted.write_text(json.dumps(PREDICTED))
    truth.write_text(json.dumps(TRUTH))
    out_dir = tmp_path / "results"
    assert score.main(["--predicted", str(predicted), "--truth", str(truth),
                       "--out-dir", str(out_dir)]) == 0
    printed = capsys.readouterr().out
    assert "by_kind" in printed and "calls confidence" in printed
    (saved,) = out_dir.glob("graph_score_expected_graph_*.json")
    data = json.loads(saved.read_text())
    assert data["overall"]["tp"] == 3
    assert data["inputs"]["truth"] == str(truth)
