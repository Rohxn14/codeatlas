"""Measure search on the polyglot fixture: recall@5 and MRR for four configurations.

    python scripts/eval_search.py [--no-vectors]

Needs the bge-small model (the cloud setup script downloads it). With `--no-vectors`, or
if the model is missing, only the BM25 row is reported.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from codeatlas.indexer.pipeline import build_graph  # noqa: E402
from codeatlas.search import HybridSearch, build_embeddings  # noqa: E402
from codeatlas.store import GraphStore  # noqa: E402

FIXTURE = ROOT / "eval" / "fixtures" / "polyglot_app"
QUERIES = ROOT / "tests" / "data" / "search" / "fixture_queries.json"
CONFIGS = {  # name -> (use bm25, use vectors, expand)
    "BM25 only": (True, False, False),
    "vectors only": (False, True, False),
    "fused": (True, True, False),
    "fused + graph": (True, True, True),
}


def ranked_keys(search: HybridSearch, query: str, bm25: bool, expand: bool) -> list[str]:
    return [h.node.key for h in search.search(query, k=10, expand=expand, bm25=bm25)]


def metrics(rows: list[tuple[list[str], list[str]]]) -> tuple[float, float]:
    recall = mrr = 0.0
    for got, want in rows:
        top5 = got[:5]
        recall += sum(w in top5 for w in want) / len(want)
        ranks = [got.index(w) + 1 for w in want if w in got]
        mrr += 1.0 / min(ranks) if ranks else 0.0
    return recall / len(rows), mrr / len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-vectors", action="store_true")
    args = parser.parse_args(argv)
    queries = json.loads(QUERIES.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory() as tmp:
        store = GraphStore(Path(tmp) / "fixture.db")
        try:
            sid = build_graph(str(FIXTURE), store).snapshot_id
            embedder = None
            if not args.no_vectors:
                try:
                    from codeatlas.llm.embeddings import EmbeddingClient

                    embedder = EmbeddingClient()
                    print(f"embedded {build_embeddings(store, sid, embedder, FIXTURE)} nodes")
                except Exception as exc:  # model missing or offline: say so, report BM25 only
                    print(f"vectors unavailable ({type(exc).__name__}: {exc}); BM25 only")
                    embedder = None
            searchers = {True: HybridSearch(store, sid, embedder),
                         False: HybridSearch(store, sid, None)}
            print(f"{'configuration':<16} recall@5   MRR")
            misses: dict[str, list[str]] = {}
            for name, (bm25, vec, expand) in CONFIGS.items():
                if vec and embedder is None:
                    continue
                rows = []
                for q in queries:
                    got = ranked_keys(searchers[vec], q["question"], bm25, expand)
                    rows.append((got, q["expected"]))
                    if not any(w in got[:5] for w in q["expected"]):
                        misses.setdefault(q["question"], []).append(name)
                r, m = metrics(rows)
                print(f"{name:<16} {r:8.3f}  {m:.3f}")
            total = 1 if embedder is None else len(CONFIGS)
            every = [q for q, c in misses.items() if len(c) == total]
            print("\nmissed (top 5) by every configuration:")
            for q in every or ["(none)"]:
                print("  " + q)
        finally:
            store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
