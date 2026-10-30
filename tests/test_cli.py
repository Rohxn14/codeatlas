import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import DATA

from codeatlas.cli import main


def scan_json(capsys: pytest.CaptureFixture[str], *args: str) -> dict:
    assert main(["scan", *args, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_scan_generic_json(capsys: pytest.CaptureFixture[str]) -> None:
    report = scan_json(capsys, str(DATA / "generic"))
    rows = {row["language"]: row for row in report["languages"]}
    assert set(rows) == {"go", "java", "rust", "markdown"}
    assert {rows[lang]["tier"] for lang in ("go", "java", "rust")} == {"structural"}
    assert rows["markdown"]["tier"] == "text"
    assert rows["go"]["files"] == 2
    assert rows["go"]["files_with_errors"] == 1
    assert rows["java"]["nodes"] == {"module": 1, "class": 2, "interface": 1, "function": 4}
    assert rows["rust"]["raw_calls"] >= 3
    assert report["snapshot"]["limits_hit"] == []
    assert report["snapshot"]["id"].startswith("generic@")


def test_every_file_in_exactly_one_row(capsys: pytest.CaptureFixture[str]) -> None:
    report = scan_json(capsys, str(DATA / "generic"))
    on_disk = [p for p in (DATA / "generic").rglob("*") if p.is_file()]
    assert report["totals"]["files"] + report["skipped"]["count"] == len(on_disk)
    assert sum(r["files"] for r in report["languages"]) == report["totals"]["files"]


def test_rows_sorted_by_size(capsys: pytest.CaptureFixture[str]) -> None:
    sizes = [r["bytes"] for r in scan_json(capsys, str(DATA / "generic"))["languages"]]
    assert sizes == sorted(sizes, reverse=True)


def test_time_limit_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "a.go").write_text("package a\n", encoding="utf-8")
    config = tmp_path / "codeatlas.toml"
    config.write_text("[limits]\nmax_seconds = 0.000001\n", encoding="utf-8")
    report = scan_json(capsys, str(tmp_path), "--config", str(config))
    assert report["snapshot"]["limits_hit"] == ["max_seconds"]


def test_text_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scan", str(DATA / "generic")]) == 0
    out = capsys.readouterr().out
    assert "Language census" in out and "structural" in out
    assert "limits hit: none" in out


def test_bad_source_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scan", str(tmp_path / "missing")]) == 2
    assert main(["scan", "https://example.com/a/b"]) == 2
    assert "github.com" in capsys.readouterr().err


def test_console_script_entry_point() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "codeatlas.cli", "scan", str(DATA / "generic"), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["totals"]["files"] == 5
