"""Hybrid search with a deterministic fake embedder: exact fusion, expansion and packing."""

import zlib
from pathlib import Path

import numpy as np
import pytest

from codeatlas.models import (
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    Resolution,
    Snapshot,
    Span,
    make_key,
    make_node_id,
    make_snapshot_id,
)
from codeatlas.search import HybridSearch, build_embeddings, context_pack, node_text, rrf
from codeatlas.search.hybrid import SearchHit
from codeatlas.store import GraphStore

SID = make_snapshot_id("demo", "a" * 12)
DIM = 32


class FakeEmbedder:
    """Hashes each word into one of 32 slots; texts sharing words are similar."""

    model = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls += len(texts)
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in text.lower().split():
                out[row, zlib.crc32(word.encode()) % DIM] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


def mk(path: str, qualname: str, kind=NodeKind.FUNCTION, lines=(1, 5), doc=None) -> Node:
    key = make_key(path, qualname)
    return Node(make_node_id(SID, key), key, SID, kind, "python", qualname.split(".")[-1],
                qualname, path, Span(*lines), signature=f"def {qualname}()", docstring=doc)


def edge(a: Node, b: Node, kind=EdgeKind.CALLS, conf=1.0) -> Edge:
    return Edge(a.id, b.id, kind, conf, Resolution.DIRECT, 1)


@pytest.fixture
def store():
    s = GraphStore(":memory:")
    s.create_snapshot(Snapshot(SID, "demo", "a" * 40, "2026-01-01T00:00:00Z", "0", "x"))
    yield s
    s.close()


def seed(store: GraphStore):
    save = mk("repo.py", "save", doc="persist rows to disk")
    load = mk("repo.py", "load", lines=(10, 14), doc="read rows back")
    helper = mk("util.py", "helper", doc="unrelated helper")
    weak = mk("util.py", "weak", doc="weak neighbour")
    store.write_nodes([save, load, helper, weak])
    store.write_edges(SID, [edge(save, helper), edge(load, save, conf=0.9),
                            edge(save, weak, conf=0.3)])
    return save, load, helper, weak


def test_rrf_two_hand_made_lists():
    scores = rrf([["a", "b", "c"], ["b", "d"]])
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["d"] == pytest.approx(1 / 62)
    assert max(scores, key=scores.get) == "b"


def test_bm25_only_when_no_embeddings_and_says_so(store):
    save, *_ = seed(store)
    search = HybridSearch(store, SID, FakeEmbedder())
    hits = search.search("persist", expand=False)
    assert hits[0].node.id == save.id and hits[0].sources == ["bm25"]
    assert any("no embeddings" in n for n in search.notes)


def test_fusion_marks_both_sources(store):
    save, *_ = seed(store)
    emb = FakeEmbedder()
    build_embeddings(store, SID, emb)
    hits = HybridSearch(store, SID, emb).search("persist rows to disk", expand=False)
    assert hits[0].node.id == save.id
    assert hits[0].sources == ["bm25", "vector"]


def test_expansion_adds_neighbours_without_duplicates_and_respects_confidence(store):
    save, load, helper, weak = seed(store)
    hits = HybridSearch(store, SID, None).search("persist", k=3, min_confidence=0.5)
    ids = [h.node.id for h in hits]
    assert ids[0] == save.id
    assert set(ids) == {save.id, helper.id, load.id}  # weak (0.3) is cut
    assert len(ids) == len(set(ids))
    graph = {h.node.id: h for h in hits[1:]}
    assert graph[helper.id].sources == ["graph"]
    assert graph[helper.id].score == pytest.approx(hits[0].score * 1.0 * 0.5)
    assert graph[load.id].score == pytest.approx(hits[0].score * 0.9 * 0.5)
    assert graph[load.id].via.src_id == load.id  # incoming edge found too
    assert weak.id not in ids


def test_no_expand(store):
    seed(store)
    hits = HybridSearch(store, SID, None).search("persist", k=1, expand=False)
    assert len(hits) == 1


def test_build_embeddings_only_missing_and_kinds(store):
    save, *_ = seed(store)
    store.write_nodes([mk("a.py", "", NodeKind.MODULE), mk("a.py", "V", NodeKind.EXTERNAL)])
    emb = FakeEmbedder()
    assert build_embeddings(store, SID, emb) == 5  # external skipped
    assert build_embeddings(store, SID, emb) == 0
    assert emb.calls == 5


def test_node_text_reads_body_with_replacement(store, tmp_path: Path):
    (tmp_path / "f.py").write_bytes(b"def f():\n    x = '\xff'\n" + b"#\n" * 30)
    n = mk("f.py", "f", lines=(1, 40))
    text = node_text(n, tmp_path)
    assert "x = '�'" in text and text.count("\n#") <= 14
    assert "x = " not in node_text(n)
    assert "def f()" in node_text(n)


def test_embedding_round_trip(store):
    save, *_ = seed(store)
    vec = np.arange(4, dtype=np.float32)
    assert store.write_embeddings([(save.id, "m", vec)]) == 1
    ids, matrix = store.embeddings(SID, "m")
    assert ids == [save.id] and matrix.dtype == np.float32
    assert np.array_equal(matrix[0], vec)
    assert store.embeddings(SID, "other")[0] == []
    store.write_embeddings([(save.id, "m", vec + 1)])  # replaces
    assert np.array_equal(store.embeddings(SID, "m")[1][0], vec + 1)


def hit(path, a, b, score, name="n"):
    return SearchHit(mk(path, name, lines=(a, b)), score, ["bm25"])


def test_context_pack_merges_overlaps_in_score_order():
    spans = context_pack([hit("a.py", 1, 10, 0.9, "x"), hit("b.py", 1, 5, 0.8, "y"),
                          hit("a.py", 8, 20, 0.7, "z")])
    assert [str(s) for s in spans] == ["a.py:1-20", "b.py:1-5"]
    assert "x" in spans[0].reason and "z" in spans[0].reason


def test_context_pack_stops_at_max_lines():
    spans = context_pack([hit("a.py", 1, 10, 0.9), hit("b.py", 1, 10, 0.8),
                          hit("c.py", 1, 10, 0.7)], max_lines=15)
    assert [str(s) for s in spans] == ["a.py:1-10", "b.py:1-5"]
    assert sum(s.lines for s in spans) == 15


def test_graph_neighbours_compete_for_the_k_places(store):
    seed(store)
    hits = HybridSearch(store, SID, None).search("persist", k=1, min_confidence=0.5)
    assert len(hits) == 1  # a neighbour may win a place, but never adds one
    scores = [h.score for h in HybridSearch(store, SID, None).search("persist", k=3)]
    assert scores == sorted(scores, reverse=True)
