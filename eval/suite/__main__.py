"""`python -m eval.suite [--only NAME] [--max N] [--skip-large]`: run the acceptance suite."""

from __future__ import annotations

import argparse
from pathlib import Path

from eval.suite.report import scoreboard
from eval.suite.repos import load_repos
from eval.suite.runner import DEFAULT_RESULTS, run_suite, select, utc_date


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.suite", description=__doc__)
    parser.add_argument("--only", metavar="NAME", help="run just this repository")
    parser.add_argument("--max", type=int, metavar="N", dest="max_repos", help="run at most N")
    parser.add_argument("--skip-large", action="store_true", help="skip large and very large")
    parser.add_argument("--time-limit", type=float, default=1800.0, help="seconds per build")
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args(argv)
    specs = select(load_repos(), args.only, args.max_repos, args.skip_large)
    if not specs:
        print("no repository matches those filters")
        return 2
    date = utc_date()
    rows = run_suite(specs, args.results_dir, date=date, time_limit=args.time_limit)
    out = args.results_dir / f"suite_{date}.md"
    out.write_text(scoreboard(rows, date), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
