"""`python -m eval.cochange [--repo NAME ...] [--path DIR] [--commits N]`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from codeatlas.indexer.intake import IntakeError
from eval.cochange.benchmark import build_queries, evaluate
from eval.cochange.predictors import CoChangePredictor, SameFolderPredictor
from eval.cochange.report import table
from eval.suite.clone import clone_pinned
from eval.suite.repos import find_repo
from eval.suite.runner import DEFAULT_RESULTS, utc_date

DEFAULT_REPOS = ("click", "cobra", "express")  # Python, Go, JavaScript


def run_on(name: str, root: Path, commits: int) -> dict[str, object]:
    """Both predictors on the same held-out queries of one repository."""
    queries = build_queries(root, commits)
    scores = [evaluate(root, queries, p) for p in (CoChangePredictor(), SameFolderPredictor())]
    return {"name": name, "queries": len(queries), "scores": scores}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.cochange", description=__doc__)
    parser.add_argument("--repo", action="append", help="suite repository name (repeatable)")
    parser.add_argument("--path", type=Path, help="a local git repository instead of the suite")
    parser.add_argument("--commits", type=int, default=100, help="held-out commits (default 100)")
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args(argv)
    results = []
    if args.path:
        results.append(run_on(args.path.name, args.path.resolve(), args.commits))
    else:
        for name in args.repo or DEFAULT_REPOS:
            try:
                root = clone_pinned(find_repo(name))
            except (IntakeError, ValueError) as exc:
                print(f"{name}: {exc}")
                # A row, not a silent gap.
                results.append({"name": name, "error": str(exc), "scores": []})
                continue
            results.append(run_on(name, root, args.commits))
    date = utc_date()
    args.results_dir.mkdir(parents=True, exist_ok=True)
    (args.results_dir / f"cochange_{date}.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    markdown = table(results, date)
    (args.results_dir / f"cochange_{date}.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
