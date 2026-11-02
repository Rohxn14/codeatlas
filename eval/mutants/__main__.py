"""`python -m eval.mutants NAME [--count N] [--seed S]`: write the mutation truth of a benchmark.

Cloud VM or container only: it runs the repository's own tests.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from codeatlas.indexer.intake import IntakeError
from eval.mutants.run import (
    TRUTH_DIR,
    WINDOWS_MESSAGE,
    Benchmark,
    load_benchmarks,
    run_benchmark,
    truth_path,
)
from eval.suite.clone import clone_pinned
from eval.suite.repos import RepoSpec

REPO_ROOT = Path(__file__).resolve().parents[2]


def source_for(bench: Benchmark) -> Path:
    """The benchmark's folder: inside this repository, or a pinned clone."""
    if bench.path:
        return (REPO_ROOT / bench.path).resolve()
    assert bench.url and bench.sha, f"{bench.name}: needs path, or url and sha"
    return clone_pinned(RepoSpec(bench.name, bench.url, bench.sha, (), "small", ""))


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        print(WINDOWS_MESSAGE)
        return 2
    parser = argparse.ArgumentParser(prog="python -m eval.mutants", description=__doc__)
    parser.add_argument("name", help="a benchmark name from benchmarks.yaml")
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds per test run")
    parser.add_argument("--venv", type=Path, help="a virtualenv whose bin/ goes first on PATH")
    parser.add_argument("--node-modules", type=Path, help="installed packages to link in")
    parser.add_argument("--out-dir", type=Path, default=TRUTH_DIR)
    args = parser.parse_args(argv)
    benches = {b.name: b for b in load_benchmarks()}
    if args.name not in benches:
        print(f"unknown benchmark {args.name!r}; known: {', '.join(benches)}")
        return 2
    bench = benches[args.name]
    try:
        root = source_for(bench)
    except IntakeError as exc:
        print(f"{bench.name}: {exc}")
        return 1
    env = {}
    if args.venv:
        import os

        env["PATH"] = str(args.venv.resolve() / "bin") + os.pathsep + os.environ.get("PATH", "")
    truth = run_benchmark(bench, root, args.count, args.seed, args.timeout, env, args.node_modules)
    out = truth_path(bench, root, args.out_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(truth, indent=2), encoding="utf-8")
    print(
        f"{bench.name}: {truth['mutants_made']} mutants made, {truth['mutants_caught']} caught "
        f"by at least one test, {truth['mutants_skipped']} skipped -> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
