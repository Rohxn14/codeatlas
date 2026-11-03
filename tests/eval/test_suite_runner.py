"""The suite runner on two local repositories: one that builds, one whose clone fails."""

import json
from pathlib import Path

from codeatlas.indexer.intake import IntakeError
from eval.suite.report import scoreboard
from eval.suite.repos import RepoSpec
from eval.suite.runner import load_rows, results_path, run_suite, select

GOOD = RepoSpec("good", "https://github.com/o/good", "a" * 40, ("python",), "small", "fine")
BAD = RepoSpec("bad", "https://github.com/o/bad", "b" * 40, ("go",), "large", "clone fails")


def test_good_and_failed_rows_then_resume(make_repo, tmp_path):
    root = make_repo(
        {
            "app/main.py": "def helper():\n    return 1\n\ndef main():\n    return helper()\n",
            "app/broken.py": "def broken(:\n",
            "README.md": "# demo\n",
        }
    )

    def cloner(spec: RepoSpec) -> Path:
        if spec is BAD:
            raise IntakeError("git clone failed: repository not found")
        return root

    messages: list[str] = []
    out = tmp_path / "results"
    rows = run_suite([GOOD, BAD], out, cloner=cloner, date="20260101", progress=messages.append)

    good, bad = rows
    assert good["status"] == "completed"
    assert good["files"] == 3
    assert good["files_by_tier"] == {"deep": 2, "text": 1}
    assert good["files_with_parse_errors"] == 1
    assert good["raw_calls"] == 1
    assert good["unresolved_share"] in (0.0, 1.0)
    assert good["nodes_by_kind"]["function"] == 3
    assert bad["status"] == "error"
    assert bad["stage"] == "clone"
    assert "repository not found" in bad["error"]
    saved = json.loads(results_path("20260101", out).read_text(encoding="utf-8"))
    assert [r["name"] for r in saved["rows"]] == ["good", "bad"]

    messages.clear()
    again = run_suite([GOOD, BAD], out, cloner=cloner, date="20260101", progress=messages.append)
    assert len(again) == 2
    assert messages == [
        "skip good: already in suite_20260101.json",
        "skip bad: already in suite_20260101.json",
    ]
    assert len(load_rows(results_path("20260101", out))) == 2


def test_scoreboard_has_one_row_per_repository_and_totals(make_repo, tmp_path):
    root = make_repo({"a.py": "def f():\n    pass\n"})

    def cloner(spec: RepoSpec) -> Path:
        if spec is BAD:
            raise IntakeError("boom | with a pipe")
        return root

    rows = run_suite([GOOD, BAD], tmp_path / "r", cloner=cloner, date="20260101", progress=str)
    text = scoreboard(rows, "20260101")
    lines = text.splitlines()
    table = [line for line in lines if line.startswith("| [")]
    assert len(table) == 2
    assert "| ok |" in table[0]
    assert "**error (clone)**" in table[1]
    assert "boom \\| with a pipe" in table[1]
    assert "- repositories: 2 run, 1 completed, 1 failed" in text


def test_select_filters():
    small = RepoSpec("s", "https://github.com/o/s", "a" * 40, ("c",), "small", "")
    specs = [small, BAD, GOOD]
    assert select(specs, None, None, skip_large=True) == [small, GOOD]
    assert select(specs, "bad", None, skip_large=False) == [BAD]
    assert select(specs, None, 2, skip_large=False) == [small, BAD]
