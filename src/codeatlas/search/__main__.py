"""`python -m codeatlas.search "query"`: print the hits for a question."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from codeatlas.search.embed import build_embeddings
from codeatlas.search.hybrid import HybridSearch, context_pack
from codeatlas.store import GraphStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m codeatlas.search")
    parser.add_argument("query")
    parser.add_argument("--db", type=Path, default=Path("codeatlas.db"))
    parser.add_argument("--snapshot", help="snapshot id (default: the newest one)")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--no-expand", action="store_true")
    parser.add_argument("--embed", action="store_true", help="build missing embeddings first")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"no database at {args.db}; index a repository first", file=sys.stderr)
        return 1
    store = GraphStore(args.db)
    try:
        snapshot_id = args.snapshot or _newest_snapshot(store)
        if snapshot_id is None:
            print("the database holds no snapshots", file=sys.stderr)
            return 1
        from codeatlas.llm.embeddings import EmbeddingClient

        embedder = EmbeddingClient.from_config()
        if args.embed:
            print(f"embedded {build_embeddings(store, snapshot_id, embedder)} new nodes")
        search = HybridSearch(store, snapshot_id, embedder)
        hits = search.search(args.query, k=args.k, expand=not args.no_expand)
        for note in search.notes:
            print(f"note: {note}")
        for hit in hits:
            n = hit.node
            print(f"{hit.score:.4f}  {n.path}:{n.span.start_line}-{n.span.end_line}  "
                  f"{n.qualname or n.path}  [{'+'.join(hit.sources)}]")
        print("\ncontext pack:")
        for span in context_pack(hits):
            print(f"  {span}  {span.reason}")
    finally:
        store.close()
    return 0


def _newest_snapshot(store: GraphStore) -> str | None:
    row = store._conn.execute(  # noqa: SLF001 - no public "list snapshots" in the store
        "SELECT id FROM snapshots ORDER BY indexed_at DESC LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


if __name__ == "__main__":
    raise SystemExit(main())
