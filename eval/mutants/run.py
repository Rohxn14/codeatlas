"""Run the mutation experiment for one benchmark: mutate on a scratch copy, run the tests.

Only this module runs a repository's tests, and only for repositories pinned in
`benchmarks.yaml`, inside the cloud VM or a container. The original checkout is never
edited: every mutant is written into a scratch copy and restored afterwards.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from codeatlas.config import Config
from codeatlas.indexer.pipeline import build_graph
from codeatlas.models import Node
from codeatlas.store import GraphStore
from eval.mutants.mutate import PYTHON_LANGUAGES, mutate_function
from eval.mutants.select import candidate_functions, pick

BENCHMARKS_FILE = Path(__file__).with_name("benchmarks.yaml")
TRUTH_DIR = Path(__file__).with_name("truth")
WINDOWS_MESSAGE = (
    "Mutation truth runs a repository's own tests, so it is for the cloud VM or a "
    "container only (CLAUDE.md, Safety). Run it in a cloud session, in CI or in WSL."
)
_SKIP_COPY = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "node_modules", ".venv")


@dataclass(frozen=True, slots=True)
class Command:
    """How to run the tests of one language."""

    run: str
    cwd: str
    reporter: str  # "pytest" or "vitest"
    pythonpath: str = ""


@dataclass(frozen=True, slots=True)
class Benchmark:
    name: str
    why: str
    commands: dict[str, Command]
    path: str | None = None
    url: str | None = None
    sha: str | None = None


def load_benchmarks(path: Path = BENCHMARKS_FILE) -> list[Benchmark]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    for entry in data["benchmarks"]:
        commands = {lang: Command(**spec) for lang, spec in entry["commands"].items()}
        out.append(
            Benchmark(
                entry["name"],
                entry["why"].strip(),
                commands,
                entry.get("path"),
                entry.get("url"),
                entry.get("sha"),
            )
        )
    return out


def command_for(commands: dict[str, Command], language: str) -> Command | None:
    """The test command for a node's language (tsx and javascript use the TypeScript one)."""
    key = "python" if language in PYTHON_LANGUAGES else "typescript"
    return commands.get(key)


def test_argv(command: Command) -> list[str]:
    """The command with the flags that make failing test ids easy to read."""
    argv = shlex.split(command.run)
    if command.reporter == "pytest":
        return [*argv, "-q", "--tb=no", "-rfE", "-p", "no:cacheprovider"]
    return [*argv, "--reporter=json"]


def failing_ids(reporter: str, output: str) -> list[str]:
    """Ids of failed tests from a runner's output, sorted."""
    ids: set[str] = set()
    if reporter == "pytest":
        for line in output.splitlines():
            if line.startswith(("FAILED ", "ERROR ")):
                ids.add(line.split(" ", 1)[1].split(" - ")[0].strip())
    else:
        start = output.find("{")
        try:
            report = json.loads(output[start:]) if start >= 0 else {}
        except ValueError:
            report = {}
        for file in report.get("testResults", []):
            name = Path(file.get("name", "")).name
            failed = [a for a in file.get("assertionResults", []) if a.get("status") == "failed"]
            ids.update(f"{name}::{a.get('fullName', '')}" for a in failed)
            if not failed and file.get("status") == "failed":
                ids.add(f"{name}::<file failed to run>")
    return sorted(ids)


def run_tests(
    scratch: Path, command: Command, timeout: float, env: dict[str, str]
) -> dict[str, object]:
    """One test run: exit status, failing ids, seconds, and whether it timed out."""
    cwd = scratch / command.cwd
    run_env = {**env}
    if command.pythonpath:
        run_env["PYTHONPATH"] = str(scratch / command.pythonpath)
    started = time.monotonic()
    try:
        done = subprocess.run(
            test_argv(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=run_env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "exit_status": None,
            "timed_out": True,
            "failing_tests": [],
            "seconds": round(time.monotonic() - started, 2),
        }
    return {
        "exit_status": done.returncode,
        "timed_out": False,
        "failing_tests": failing_ids(command.reporter, done.stdout),
        "seconds": round(time.monotonic() - started, 2),
    }


def run_benchmark(
    bench: Benchmark,
    source_root: Path,
    count: int = 30,
    seed: int = 0,
    timeout: float = 120.0,
    env: dict[str, str] | None = None,
    node_modules: Path | None = None,
) -> dict[str, object]:
    """Mutate up to `count` functions of `source_root` one at a time and record the failures."""
    env = {**os.environ, **(env or {})}
    with tempfile.TemporaryDirectory(prefix="codeatlas-mutants-") as tmp:
        db = Path(tmp) / "graph.db"
        with GraphStore(db) as store:
            result = build_graph(str(source_root), store, Config())
            pool = candidate_functions(store, result.snapshot_id)
        chosen = pick(pool.functions, count, seed)
        scratch = Path(tmp) / "work"
        shutil.copytree(source_root, scratch, ignore=_SKIP_COPY)
        _link_node_modules(scratch, bench, node_modules)
        baselines = {
            lang: run_tests(scratch, cmd, timeout, env) for lang, cmd in bench.commands.items()
        }
        _require_usable(baselines)
        mutants = [_run_mutant(n, scratch, bench, baselines, timeout, env) for n in chosen]
    caught = sum(1 for m in mutants if m.get("failing_tests"))
    made = [m for m in mutants if m["status"] == "mutated"]
    return {
        "repo": bench.name,
        "source": bench.url or bench.path,
        "seed": seed,
        "candidates": len(pool.functions),
        "caller_basis": pool.basis,
        "test_commands": {lang: c.run for lang, c in bench.commands.items()},
        "baseline": baselines,
        "mutants_made": len(made),
        "mutants_caught": caught,
        "mutants_skipped": len(mutants) - len(made),
        "mutants": mutants,
    }


def _require_usable(baselines: dict[str, dict[str, object]]) -> None:
    """Stop when the unmutated tests cannot run: every mutant would then look "caught"."""
    for language, base in baselines.items():
        if base["timed_out"] or base["exit_status"] not in (0, 1):
            raise RuntimeError(
                f"the unmutated {language} tests did not run cleanly (exit status "
                f"{base['exit_status']}, timed out {base['timed_out']}): install the "
                "repository's test dependencies first (see --venv and --node-modules)"
            )


def _link_node_modules(scratch: Path, bench: Benchmark, node_modules: Path | None) -> None:
    """Point the scratch TypeScript folder at already-installed packages (nothing is installed)."""
    command = bench.commands.get("typescript")
    if node_modules is None or command is None:
        return
    target = scratch / command.cwd / "node_modules"
    if not target.exists():
        target.symlink_to(node_modules.resolve(), target_is_directory=True)


def _run_mutant(
    node: Node,
    scratch: Path,
    bench: Benchmark,
    baselines: dict[str, dict[str, object]],
    timeout: float,
    env: dict[str, str],
) -> dict[str, object]:
    record: dict[str, object] = {"function": node.key, "language": node.language}
    command = command_for(bench.commands, node.language)
    if command is None:
        return {**record, "status": "skipped", "reason": f"no test command for {node.language}"}
    target = scratch.joinpath(*node.path.split("/"))
    original = target.read_bytes()
    mutation = mutate_function(
        node.language,
        original,
        node.name,
        node.span.start_line,
        node.span.end_line,
        node.span.end_col,
    )
    if mutation.text is None:
        return {**record, "status": "skipped", "reason": mutation.reason}
    key = "python" if node.language in PYTHON_LANGUAGES else "typescript"
    known = set(baselines[key]["failing_tests"])  # type: ignore[arg-type]
    try:
        target.write_bytes(mutation.text)
        outcome = run_tests(scratch, command, timeout, env)
    finally:
        target.write_bytes(original)
    failing = [t for t in outcome["failing_tests"] if t not in known]  # type: ignore[union-attr]
    return {
        **record,
        "status": "mutated",
        "mutation": mutation.description,
        "failing_tests": failing,
        "seconds": outcome["seconds"],
        "exit_status": outcome["exit_status"],
        "timed_out": outcome["timed_out"],
    }


def truth_path(bench: Benchmark, source_root: Path, out_dir: Path = TRUTH_DIR) -> Path:
    """`<repo>_<sha12>.json`; a fixture folder uses its own tree hash, as the oracle does."""
    ref = bench.sha or _tree_hash(source_root)
    return out_dir / f"{bench.name}_{ref[:12]}.json"


def _tree_hash(folder: Path) -> str:
    top = subprocess.run(
        ["git", "-C", str(folder), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    rel = folder.resolve().relative_to(Path(top).resolve()).as_posix() if top else "."
    done = subprocess.run(
        ["git", "-C", top or str(folder), "rev-parse", f"HEAD:{rel}" if rel != "." else "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() or "unknown".ljust(12, "0")
