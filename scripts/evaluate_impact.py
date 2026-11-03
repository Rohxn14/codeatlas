"""Score the impact engine: mutation truth, held-out commits, and the baselines.

    python scripts/evaluate_impact.py mutants [--benchmark NAME ...] [--combine max|noisy_or]
    python scripts/evaluate_impact.py cochange [--repo NAME ...] [--commits N]

`mutants` indexes each benchmark's source with `build_graph`, reads
`eval/mutants/truth/*.json` and prints one table per benchmark. `cochange` runs the
held-out-commit benchmark with the existing predictors plus the engine, building one
index per repository. Neither runs repository code: they read git and parse files.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from codeatlas.impact.engine import ImpactEngine  # noqa: E402
from codeatlas.impact.evaluate import (  # noqa: E402
    default_selectors,
    evaluate_mutants,
    mutants_from_truth,
    table,
)
from codeatlas.impact.models import ImpactConfig  # noqa: E402
from codeatlas.indexer.intake import IntakeError  # noqa: E402
from codeatlas.indexer.pipeline import build_graph  # noqa: E402
from codeatlas.store import GraphStore  # noqa: E402


def run_mutants(args: argparse.Namespace) -> int:
    from eval.mutants.__main__ import source_for
    from eval.mutants.run import TRUTH_DIR, load_benchmarks, truth_path

    config = replace(ImpactConfig(), combine=args.combine, depth=args.depth,
                     decay=args.decay, test_threshold=args.threshold)
    report, results = [], {}
    for bench in load_benchmarks():
        if args.benchmark and bench.name not in args.benchmark:
            continue
        try:
            root = source_for(bench)
        except IntakeError as exc:
            report.append(f"### {bench.name}\n\nnot run: {exc}\n")
            continue
        truth_file = truth_path(bench, root, TRUTH_DIR)
        if not truth_file.exists():
            report.append(f"### {bench.name}\n\nnot run: no truth file {truth_file.name}\n")
            continue
        truth = json.loads(truth_file.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            store = GraphStore(Path(tmp) / "bench.db")
            try:
                built = build_graph(str(root), store)
                engine = ImpactEngine(store, built.snapshot_id, config)
                result = evaluate_mutants(engine, mutants_from_truth(truth), default_selectors())
            finally:
                store.close()
        results[bench.name] = result
        report.append(table(bench.name, result))
    text = "\n".join(report)
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        args.out.with_suffix(".json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


def run_cochange(args: argparse.Namespace) -> int:
    from eval.cochange.benchmark import build_queries, evaluate
    from eval.cochange.predictors import CoChangePredictor, ImpactPredictor, SameFolderPredictor
    from eval.cochange.report import table as cochange_table
    from eval.suite.clone import clone_pinned
    from eval.suite.repos import find_repo
    from eval.suite.runner import utc_date

    results = []
    for name in args.repo or ("click", "cobra", "express"):
        try:
            root = clone_pinned(find_repo(name))
        except (IntakeError, ValueError) as exc:
            print(f"{name}: {exc}")
            results.append({"name": name, "error": str(exc), "scores": []})
            continue
        queries = build_queries(root, args.commits)
        with tempfile.TemporaryDirectory() as tmp:
            store = GraphStore(Path(tmp) / "repo.db")
            try:
                built = build_graph(str(root), store)
                predictors = [CoChangePredictor(), SameFolderPredictor(),
                              ImpactPredictor(store, built.snapshot_id)]
                scores = [evaluate(root, queries, p) for p in predictors]
            finally:
                store.close()
        results.append({"name": name, "queries": len(queries), "scores": scores})
    text = cochange_table(results, utc_date())
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("mutants")
    m.add_argument("--benchmark", action="append")
    m.add_argument("--combine", choices=["max", "noisy_or"], default="max")
    m.add_argument("--depth", type=int, default=ImpactConfig().depth)
    m.add_argument("--decay", type=float, default=ImpactConfig().decay)
    m.add_argument("--threshold", type=float, default=ImpactConfig().test_threshold)
    m.add_argument("--out", type=Path)
    m.set_defaults(run=run_mutants)
    c = sub.add_parser("cochange")
    c.add_argument("--repo", action="append")
    c.add_argument("--commits", type=int, default=100)
    c.add_argument("--out", type=Path)
    c.set_defaults(run=run_cochange)
    args = parser.parse_args(argv)
    return int(args.run(args))


if __name__ == "__main__":
    raise SystemExit(main())
