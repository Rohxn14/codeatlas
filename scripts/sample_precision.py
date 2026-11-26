"""Measure how often CALLS edges are right on a real repository: sample, label, score.

    python scripts/sample_precision.py sample --db click.db --root path/to/click --out sample.json
    python scripts/sample_precision.py score sample_labelled.json [--edges direct=2073 ...]

`sample` draws a fixed random sample (seed 27) of CALLS edges per stratum, the way each was
found: `direct`, `self_method`, `import_scoped`, `name_guess`, and `external` (a direct call
to something outside the repository). Each row carries the evidence a person needs to judge
it: the call as written, that line of code, and the definition the edge points at.

Labelling is done by reading the code, one row at a time, with one rule fixed in advance:
an edge is right if this call can run that function in some real execution of the code,
and wrong if it cannot. Each labelled row gets `right` (true or false) and a `reason`.

`score` prints precision per stratum with a 95% Wilson interval and the stratum's mean
confidence, so the confidence can be compared with how often edges are right. With the
number of edges per stratum (`--edges`), it also gives the share of all CALLS edges right.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from codeatlas.models import EdgeKind  # noqa: E402
from codeatlas.store import GraphStore  # noqa: E402

STRATA = {"direct": 20, "self_method": 20, "import_scoped": 20, "name_guess": 20, "external": 10}
SEED = 27


def stratum(edge_dst: str, resolution: str) -> str:
    return "external" if "::external:" in edge_dst else resolution


def sample(db: Path, root: Path, seed: int = SEED) -> tuple[list[dict], dict[str, int]]:
    """The sample's rows, and how many CALLS edges each stratum has in the snapshot."""
    with GraphStore(db) as store:
        sid = store.snapshots()[0].id
        prefix = sid + "/"
        nodes = {n.id: n for n in store.nodes(sid)}
        raw = defaultdict(list)
        for call, _resolved in store.raw_calls(sid):
            raw[(call.caller_key, call.line)].append(call)
        strata: dict[str, list] = defaultdict(list)
        for e in store.edges(sid):
            if e.kind is EdgeKind.CALLS:
                strata[stratum(e.dst_id, str(e.resolution))].append(e)
    rng = random.Random(seed)
    rows = []
    for name, n in STRATA.items():
        pool = sorted(strata[name], key=lambda e: (e.src_id, e.dst_id, e.line or 0))
        for e in rng.sample(pool, min(n, len(pool))):
            caller, target = nodes[e.src_id], nodes.get(e.dst_id)
            lines = (root / caller.path).read_text(encoding="utf-8").splitlines()
            rows.append({
                "n": len(rows) + 1, "stratum": name, "confidence": round(e.confidence, 3),
                "candidates": e.attrs.get("candidates", 1), "caller": caller.key, "line": e.line,
                "code": lines[e.line - 1].strip()[:160] if e.line else "",
                "as_written": [c.callee_text for c in raw[(caller.key, e.line)]],
                "target": e.dst_id.removeprefix(prefix),
                "target_signature": (target.signature or "")[:120] if target else "",
            })
    return rows, {name: len(edges) for name, edges in strata.items()}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """A 95% interval for a share k/n that stays sensible for small n and k near 0 or n."""
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def score(rows: list[dict], edges: dict[str, int]) -> str:
    out = ["| stratum | right | precision | 95% interval | mean confidence | edges |",
           "| --- | --- | --- | --- | --- | --- |"]
    total = right = 0.0
    for name in STRATA:
        mine = [r for r in rows if r["stratum"] == name]
        if not mine:
            continue
        k = sum(bool(r["right"]) for r in mine)
        lo, hi = wilson(k, len(mine))
        mean = sum(r["confidence"] for r in mine) / len(mine)
        count = edges.get(name, 0)
        out.append(f"| {name} | {k}/{len(mine)} | {k / len(mine):.2f} | {lo:.2f}-{hi:.2f} | "
                   f"{mean:.2f} | {count:,} |")
        total += count
        right += count * k / len(mine)
    if total:
        out.append(f"\nWeighted by the edges in each stratum, about {right / total:.0%} of all "
                   "CALLS edges are right.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--db", type=Path, required=True)
    s.add_argument("--root", type=Path, required=True, help="the indexed checkout")
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--seed", type=int, default=SEED)
    c = sub.add_parser("score")
    c.add_argument("labelled", type=Path)
    args = parser.parse_args(argv)
    if args.command == "sample":
        rows, edges = sample(args.db, args.root, args.seed)
        args.out.write_text(json.dumps({"edges": edges, "rows": rows}, indent=1) + "\n",
                            encoding="utf-8")
        print(f"{len(rows)} rows written to {args.out}; edges per stratum: {edges}")
        return 0
    data = json.loads(args.labelled.read_text(encoding="utf-8"))
    print(score(data["rows"], data["edges"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
