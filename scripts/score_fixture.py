"""Index the polyglot fixture and score the graph against its hand labels.

    python scripts/score_fixture.py [--truth PATH] [--export PATH] [--kinds calls,imports]

Every resolver task measures itself with this one command, on Windows and Linux. It
builds the graph in a temporary database with `build_graph`, exports it in the
contract's section 8 shape, and runs the scorer from `eval/oracle`. Pass `--truth` with
an `eval/oracle/references/oracle_*.json` file to score against the SCIP oracle instead.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "eval" / "fixtures" / "polyglot_app"
sys.path.insert(0, str(ROOT))  # the eval package lives at the repository root
sys.path.insert(0, str(ROOT / "src"))  # works before `pip install -e .` too

from codeatlas.indexer.pipeline import build_graph  # noqa: E402
from codeatlas.store import GraphStore  # noqa: E402
from eval.oracle.graph import parse_graph  # noqa: E402
from eval.oracle.score import render, score  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--truth", type=Path, default=FIXTURE / "expected_graph.json")
    parser.add_argument("--export", type=Path, help="also save the graph export here")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        store = GraphStore(Path(tmp) / "fixture.db")
        try:
            built = build_graph(str(FIXTURE), store)
            export = store.export_json(built.snapshot_id)
        finally:
            store.close()
    if args.export:
        args.export.write_text(json.dumps(export, indent=1) + "\n", encoding="utf-8")
    truth = parse_graph(json.loads(args.truth.read_text(encoding="utf-8")))
    print(render(score(parse_graph(export), truth)))
    print()
    print(f"edges written: {built.edges_written}; raw calls resolved: "
          f"{built.resolved_calls} of {built.raw_calls}")
    if built.languages_without_resolver:
        print("languages without a resolver: " + ", ".join(built.languages_without_resolver))
    for problem in built.problems:
        print(f"problem: {problem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
