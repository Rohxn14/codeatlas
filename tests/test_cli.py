import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import DATA

from codeatlas import cli
from codeatlas import config as config_module
from codeatlas.cli import main, scan, skipped_result
from codeatlas.config import Config
from codeatlas.indexer.intake import open_source
from codeatlas.indexer.pipeline import parse as parse_module
from codeatlas.indexer.pipeline.parse import parse_file
from codeatlas.indexer.registry import Registry
from codeatlas.models import Tier


def scan_json(capsys: pytest.CaptureFixture[str], *args: str) -> dict:
    assert main(["scan", *args, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_scan_generic_json(capsys: pytest.CaptureFixture[str]) -> None:
    report = scan_json(capsys, str(DATA / "generic"))
    rows = {row["language"]: row for row in report["languages"]}
    assert set(rows) == {"go", "java", "rust", "ruby", "markdown"}
    assert {rows[lang]["tier"] for lang in ("go", "java", "rust", "ruby")} == {"structural"}
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
    in_skipped_folders = sum(entry["file_count"] for entry in report["skipped_paths"])
    assert report["totals"]["files"] + in_skipped_folders == len(on_disk)
    assert sum(r["files"] for r in report["languages"]) == report["totals"]["files"]


def test_skipped_folders_and_files_are_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    for name in ("a.js", "b.js", "c.js"):
        (tmp_path / "node_modules" / "pkg" / name).write_text("x\n", encoding="utf-8")
    (tmp_path / "app.min.js").write_text("var a=1;\n", encoding="utf-8")
    (tmp_path / "logo.go").write_bytes(b"\x00\x01binary")
    (tmp_path / "main.go").write_text("package main\n", encoding="utf-8")
    report = scan_json(capsys, str(tmp_path))
    assert report["skipped_paths"] == [
        {"path": "node_modules", "reason": "excluded directory", "file_count": 3}
    ]
    assert report["skipped_files"]["by_reason"] == {"binary": 1, "minified": 1}
    rows = {(r["language"], r["tier"]): r["files"] for r in report["languages"]}
    assert rows == {("go", "structural"): 1, ("go", "text"): 1, ("javascript", "text"): 1}
    assert report["totals"]["files"] == 3

    assert main(["scan", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "node_modules (excluded directory, 3 files)" in out
    assert "not parsed, kept as text: 2 files" in out


def test_skipped_files_become_text_nodes_with_reason(tmp_path: Path) -> None:
    (tmp_path / "logo.go").write_bytes(b"\x00\x01binary")
    (tmp_path / "notes.weird").write_text("hi\n", encoding="utf-8")
    report = scan(str(tmp_path), Config())
    rows = {(r.language, r.tier) for r in report.rows}
    assert rows == {("go", "text"), ("text", "text")}
    record = next(f for f in report.discovery.files if f.path == "logo.go")
    result = skipped_result(record, "binary", report.snapshot.id)
    assert result.tier is Tier.TEXT
    assert result.nodes[0].attrs == {"skipped_reason": "binary"}


def test_unknown_extension_records_a_reason(tmp_path: Path) -> None:
    (tmp_path / "notes.weird").write_text("hi\n", encoding="utf-8")
    report = scan(str(tmp_path), Config())
    record = report.discovery.files[0]
    result = parse_file(open_source(str(tmp_path), Config()), record, Registry(), "s@1")
    assert result.nodes[0].attrs["tier_reason"] == cli.UNKNOWN_TYPE_REASON


def test_unreadable_file_counts_as_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A file that disappears or is locked between discovery and parsing is still counted."""
    (tmp_path / "main.go").write_text("package main\n", encoding="utf-8")
    real_discover = parse_module.discover

    def denied(_self: Path) -> bytes:
        raise PermissionError("denied")

    def discover_then_lock(*args: object, **kwargs: object) -> object:
        found = real_discover(*args, **kwargs)
        monkeypatch.setattr(Path, "read_bytes", denied)
        return found

    monkeypatch.setattr(parse_module, "discover", discover_then_lock)
    report = scan(str(tmp_path), Config())
    assert [(r.language, r.tier, r.files) for r in report.rows] == [("go", "text", 1)]


def test_time_limit_starts_after_intake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A slow clone must not use up the index budget."""
    (tmp_path / "a.go").write_text("package a\n", encoding="utf-8")
    clock = [0.0]
    monkeypatch.setattr(config_module.time, "monotonic", lambda: clock[0])
    real_open = parse_module.open_source

    def slow_open(source: str, config: Config) -> object:
        clock[0] += 10_000  # far beyond max_seconds
        return real_open(source, config)

    monkeypatch.setattr(parse_module, "open_source", slow_open)
    report = scan(str(tmp_path), Config())
    assert report.snapshot.limits_hit == ()
    assert report.rows[0].unparsed == 0


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
    assert json.loads(done.stdout)["totals"]["files"] == 6
