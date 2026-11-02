"""Run the acceptance suite: clone, index in a child process, and keep one row per repository.

A failed clone, a crash or a timeout becomes a row with the error, never an exception
out of the runner. The repository is only ever read: nothing in it is installed, built
or executed.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from codeatlas.indexer.intake import IntakeError
from eval.suite.clone import DEFAULT_CLONES, clone_pinned
from eval.suite.repos import RepoSpec

DEFAULT_RESULTS = Path("eval") / "results"
DEFAULT_TIME_LIMIT = 1800.0  # wall-clock seconds for one repository's build
_ERROR_LIMIT = 500

Cloner = Callable[[RepoSpec], Path]


def utc_date() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def results_path(date: str, results_dir: Path = DEFAULT_RESULTS) -> Path:
    return results_dir / f"suite_{date}.json"


def load_rows(path: Path) -> list[dict[str, object]]:
    """Rows saved earlier today, or none; a damaged file is treated as empty."""
    try:
        return list(json.loads(path.read_text(encoding="utf-8")).get("rows", []))
    except (OSError, ValueError):
        return []


def save_rows(path: Path, date: str, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": date, "rows": rows}, indent=2), encoding="utf-8")


def select(
    specs: list[RepoSpec], only: str | None, max_repos: int | None, skip_large: bool
) -> list[RepoSpec]:
    """The repositories to run, in list order, after the command-line filters."""
    chosen = [
        s for s in specs if (only is None or s.name == only) and not (skip_large and s.is_large)
    ]
    return chosen[:max_repos] if max_repos is not None else chosen


def run_repo(
    spec: RepoSpec,
    cloner: Cloner,
    work_dir: Path,
    time_limit: float = DEFAULT_TIME_LIMIT,
    build_seconds: float = 300.0,
) -> dict[str, object]:
    """One scoreboard row; any failure is recorded in `error`."""
    row: dict[str, object] = {
        "name": spec.name,
        "url": spec.url,
        "sha": spec.sha,
        "size": spec.size,
        "declared_languages": list(spec.languages),
    }
    try:
        root = cloner(spec)
    except (IntakeError, OSError, ValueError) as exc:
        return {**row, "status": "error", "stage": "clone", "error": str(exc)[:_ERROR_LIMIT]}
    out = work_dir / f"{spec.name}.json"
    out.unlink(missing_ok=True)
    command = [
        sys.executable,
        "-m",
        "eval.suite.worker",
        str(root),
        str(work_dir / f"{spec.name}.db"),
        str(out),
        str(build_seconds),
    ]
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=time_limit,
            check=False,
            cwd=Path(__file__).resolve().parents[2],
        )
    except subprocess.TimeoutExpired:
        return {
            **row,
            "status": "error",
            "stage": "build",
            "error": f"timed out after {time_limit:.0f} s",
        }
    if done.returncode != 0 or not out.is_file():
        tail = (done.stderr.strip().splitlines() or [f"exit status {done.returncode}"])[-1]
        return {**row, "status": "error", "stage": "build", "error": tail[:_ERROR_LIMIT]}
    return {**row, "status": "completed", **json.loads(out.read_text(encoding="utf-8"))}


def run_suite(
    specs: list[RepoSpec],
    results_dir: Path = DEFAULT_RESULTS,
    clones_dir: Path = DEFAULT_CLONES,
    cloner: Cloner | None = None,
    date: str | None = None,
    time_limit: float = DEFAULT_TIME_LIMIT,
    build_seconds: float = 300.0,
    progress: Callable[[str], None] = print,
) -> list[dict[str, object]]:
    """Run each spec not already in today's file, saving after every repository (resume)."""
    date = date or utc_date()
    path = results_path(date, results_dir)
    rows = load_rows(path)
    done = {r["name"] for r in rows}
    cloner = cloner or (lambda spec: clone_pinned(spec, clones_dir))
    with tempfile.TemporaryDirectory(prefix="codeatlas-suite-") as tmp:
        for spec in specs:
            if spec.name in done:
                progress(f"skip {spec.name}: already in {path.name}")
                continue
            progress(f"run  {spec.name} ({spec.size})")
            rows.append(run_repo(spec, cloner, Path(tmp), time_limit, build_seconds))
            save_rows(path, date, rows)
            progress(f"     -> {rows[-1]['status']}")
    return rows
