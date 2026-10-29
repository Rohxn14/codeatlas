import json
from pathlib import Path

import pytest
from helpers import DATA, write

from codeatlas.cli import main, render, scan
from codeatlas.config import Config, Limits


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def test_scan_generic_json(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(capsys, "scan", str(DATA / "generic"), "--json")
    assert code == 0
    report = json.loads(out)
    rows = {r["language"]: r for r in report["languages"]}
    assert set(rows) == {"go", "java", "rust"}
    assert {r["tier"] for r in rows.values()} == {"structural"}
    assert rows["rust"]["nodes"] == {"module": 1, "interface": 1, "class": 1, "function": 5}
    assert rows["java"]["calls"] == 4
    assert report["totals"]["files"] == report["totals"]["files_in_rows"] == 3
    assert report["snapshot"]["limits_hit"] == []


def test_scan_text_output(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(capsys, "scan", str(DATA / "generic"))
    assert code == 0
    assert "Language census" in out
    assert "Files: 3 discovered, 3 in rows, 3 parsed, 0 skipped" in out
    assert "Limits hit: none" in out


def test_every_file_lands_in_one_row(tmp_path: Path) -> None:
    write(tmp_path, "a.go", "package a\nfunc A() { B() }\n")
    write(tmp_path, "b.kt", "fun b() {}\n")
    write(tmp_path, "c.md", "# c\n")
    write(tmp_path, "d", "no extension\n")
    write(tmp_path, "e.png", b"\x00\x01")
    write(tmp_path, "broken.rs", "fn broken( {\n")
    report = scan(str(tmp_path), Config())
    rows = {r["language"]: r for r in report["languages"]}
    assert {lang: r["files"] for lang, r in rows.items()} == {
        "go": 1, "kotlin": 1, "markdown": 1, "text": 1, "rust": 1
    }
    assert rows["kotlin"]["tier"] == "text"
    assert rows["rust"]["files_with_errors"] == 1
    assert report["totals"]["files"] == sum(r["files"] for r in rows.values()) == 5
    assert report["skipped"] == [{"path": "e.png", "reason": "binary"}]
    # Outside git, the snapshot SHA is a hash of the contents, so it is stable.
    assert scan(str(tmp_path), Config())["snapshot"]["id"] == report["snapshot"]["id"]


def test_limits_are_reported(tmp_path: Path) -> None:
    for i in range(4):
        write(tmp_path, f"m{i}.go", "package m\n")
    report = scan(str(tmp_path), Config(limits=Limits(max_files=2)))
    assert report["snapshot"]["limits_hit"] == ["max_files"]
    assert report["totals"]["files"] == 2
    assert "Limits hit: max_files" in render(report)


def test_time_limit_keeps_what_was_indexed(tmp_path: Path) -> None:
    write(tmp_path, "a.go", "package a\n")
    report = scan(str(tmp_path), Config(limits=Limits(max_seconds=1e-9)))
    assert "max_seconds" in report["snapshot"]["limits_hit"]


def test_bad_source_exits_2(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert main(["scan", str(tmp_path / "missing")]) == 2
    assert main(["scan", "https://gitlab.com/a/b"]) == 2
    assert "only github.com" in capsys.readouterr().err


@pytest.mark.live
def test_scan_public_github_repo(tmp_path: Path) -> None:
    config = Config(workdir=tmp_path)
    report = scan("https://github.com/pallets/click", config)
    assert any(r["language"] == "python" for r in report["languages"])
