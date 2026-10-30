"""Run the SCIP indexers on a repository and write its oracle file.

    python -m eval.oracle.run path/to/repo [--nodes export.json] [--out-dir DIR]

`scip-python` indexes the Python code and `scip-typescript` each TypeScript/JavaScript
project (one per `tsconfig.json`, or the repository root with an inferred config).
Both are static analysers: they read source and type stubs, never import or run the
repository's code. The runner never installs anything in the repository either, so
types from third-party packages resolve only if `node_modules` is already there; calls
between the repository's own files do not need them.

Output: `oracle_<repo>_<sha12>.json` in the graph export shape, edges of kind `calls`
with resolution `scip`, plus an `errors` list naming any indexer that failed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eval.oracle.convert import oracle_graph, path_prefix
from eval.oracle.graph import language_of_path, load_graph
from eval.oracle.scip import Index, read_index

DEFAULT_OUT = Path(__file__).parent / "references"
INSTALL_HINT = "npm install -g @sourcegraph/scip-python @sourcegraph/scip-typescript"
TIMEOUT_SECONDS = 1800
_SKIP_DIRS = frozenset({"node_modules", "__pycache__", "venv", "dist", "build"})


@dataclass(frozen=True, slots=True)
class Job:
    """One indexer invocation."""

    tool: str
    args: tuple[str, ...]
    cwd: Path
    output: Path


def tool_version(tool: str) -> str | None:
    """The tool's `--version` output, or None when it is not installed."""
    if shutil.which(tool) is None:
        return None
    done = subprocess.run([tool, "--version"], capture_output=True, text=True, timeout=60)
    return done.stdout.strip() or done.stderr.strip() or "unknown"


def source_files(repo: Path) -> list[str]:
    """Repo-relative paths of Python and TS/JS files, skipping dependency and hidden folders."""
    found = []
    for path in repo.rglob("*"):
        rel = path.relative_to(repo)
        if any(part in _SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]):
            continue
        if path.is_file() and language_of_path(rel.as_posix()) != "text":
            found.append(rel.as_posix())
    return sorted(found)


def plan_jobs(repo: Path, files: Sequence[str], name: str, sha12: str, work: Path) -> list[Job]:
    jobs: list[Job] = []
    if any(language_of_path(f) == "python" for f in files):
        jobs.append(Job(
            "scip-python",
            ("index", "--project-name", name, "--project-version", sha12, "--quiet"),
            repo,
            work / "python.scip",
        ))
    if not any(language_of_path(f) != "python" for f in files):
        return jobs
    configs = sorted(
        p.parent for p in repo.rglob("tsconfig.json")
        if not any(part in _SKIP_DIRS for part in p.relative_to(repo).parts)
    )
    if not configs:
        jobs.append(Job("scip-typescript", ("index", "--infer-tsconfig", "--no-progress-bar"),
                        repo, work / "ts_root.scip"))
    for i, folder in enumerate(configs):
        jobs.append(Job("scip-typescript", ("index", "--no-progress-bar"), folder,
                        work / f"ts_{i}.scip"))
    return jobs


def run_job(job: Job) -> str | None:
    """Run one indexer; returns an error message, or None on success."""
    command = [job.tool, *job.args, "--output", str(job.output)]
    try:
        done = subprocess.run(command, cwd=job.cwd, capture_output=True, text=True,
                              timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return f"{job.tool} in {job.cwd}: timed out after {TIMEOUT_SECONDS}s"
    if done.returncode != 0 or not job.output.exists():
        tail = (done.stderr or done.stdout).strip().splitlines()[-5:]
        return f"{job.tool} in {job.cwd}: exit {done.returncode}: " + " | ".join(tail)
    return None


def head_sha(repo: Path) -> str:
    done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                          text=True)
    return done.stdout.strip() if done.returncode == 0 else "unknown"


def build_oracle(
    repo: Path, name: str, nodes_file: Path | None, keep_scip: Path | None
) -> dict[str, object]:
    sha = head_sha(repo)
    files = source_files(repo)
    errors: list[str] = []
    indexes: list[tuple[Index, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        work = keep_scip or Path(tmp)
        work.mkdir(parents=True, exist_ok=True)
        for job in plan_jobs(repo, files, name, sha[:12], work):
            if tool_version(job.tool) is None:
                errors.append(f"{job.tool} is not installed; install with: {INSTALL_HINT}")
                continue
            error = run_job(job)
            if error:
                errors.append(error)
                continue
            index = read_index(job.output)
            indexes.append((index, path_prefix(index, repo.resolve().as_uri())))
    nodes = load_graph(nodes_file).nodes.values() if nodes_file else ()
    snapshot = {
        "id": f"{name}@{sha[:12]}", "repo": name, "commit_sha": sha,
        "indexed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "indexer_version": ", ".join(
            f"{t} {tool_version(t) or 'missing'}" for t in ("scip-python", "scip-typescript")
        ),
        "source": str(repo), "limits_hit": [],
    }
    return oracle_graph(snapshot, indexes, nodes, errors)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", type=Path)
    parser.add_argument("--name", help="repository name (default: the folder name)")
    parser.add_argument("--nodes", type=Path,
                        help="graph file whose function and test spans add caller scopes")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--keep-scip", type=Path, help="folder to keep the .scip files in")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    name = args.name or repo.name
    oracle = build_oracle(repo, name, args.nodes, args.keep_scip)
    snapshot = oracle["snapshot"]
    assert isinstance(snapshot, dict)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"oracle_{name}_{str(snapshot['commit_sha'])[:12]}.json"
    out.write_text(json.dumps(oracle, indent=1) + "\n", encoding="utf-8")
    edges, nodes, errors = (oracle[k] for k in ("edges", "nodes", "errors"))
    assert isinstance(edges, list) and isinstance(nodes, list) and isinstance(errors, list)
    print(f"{len(nodes)} nodes, {len(edges)} reference edges -> {out}")
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    return 1 if errors and not edges else 0


if __name__ == "__main__":
    raise SystemExit(main())
