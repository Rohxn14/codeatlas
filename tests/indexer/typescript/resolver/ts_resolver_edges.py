"""Index the sample project with the real pipeline and read its edges back (test helper)."""

import shutil
from pathlib import Path

from codeatlas.indexer.pipeline import build_graph
from codeatlas.store import GraphStore

SAMPLES = Path(__file__).resolve().parents[3] / "data" / "typescript_resolver"


class Edges:
    """The sample project's graph, with small queries so each test reads like a sentence."""

    def __init__(self, export: dict) -> None:
        self.rows = [e for e in export["edges"] if not e["dst_key"].startswith("::external:")]
        self.all = export["edges"]

    def out(self, kind: str, src: str, externals: bool = False) -> dict[str, tuple]:
        """target key -> (resolution, confidence, line) for one source and edge kind."""
        rows = self.all if externals else self.rows
        return {
            e["dst_key"]: (e["resolution"], round(e["confidence"], 3), e["line"])
            for e in rows
            if e["kind"] == kind and e["src_key"] == src
        }


def build(work: Path) -> Edges:
    """Copy the sample project to `work` (so no repo config interferes) and index it."""
    root = work / "proj"
    shutil.copytree(SAMPLES / "proj", root)
    store = GraphStore(":memory:")
    built = build_graph(str(root), store)
    try:
        return Edges(store.export_json(built.snapshot_id))
    finally:
        store.close()
