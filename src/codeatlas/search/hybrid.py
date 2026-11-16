"""Hybrid search: BM25 + vectors fused by rank, then one hop along the graph."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from codeatlas.models import Edge, EdgeKind, Node, NodeKind, Span
from codeatlas.search.embed import Embedder
from codeatlas.store import GraphStore

RRF_K = 60
POOL = 50
EXPAND_KINDS = (EdgeKind.CALLS, EdgeKind.CONTAINS, EdgeKind.INHERITS)
GRAPH_DISCOUNT = 0.5
# What every section node's id holds (contract section 4: `{path}::section:{title}`).
SECTION_MARK = "::section:"


@dataclass(slots=True)
class SearchHit:
    """One ranked node, with why it is here."""

    node: Node
    score: float
    sources: list[str] = field(default_factory=list)  # "bm25", "vector", "graph"
    via: Edge | None = None  # for graph hits: the edge that brought it in


def rrf(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """Reciprocal rank fusion: each list gives 1/(k+rank) to its items, rank from 1.

    Ranks, not raw scores, because BM25 and cosine live on unrelated scales.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores


class HybridSearch:
    def __init__(self, store: GraphStore, snapshot_id: str, embedder: Embedder | None) -> None:
        self.store = store
        self.snapshot_id = snapshot_id
        self.embedder = embedder
        self.notes: list[str] = []  # human-readable remarks about the last search
        self._ids: list[str] | None = None
        self._matrix: np.ndarray | None = None
        self._norms: np.ndarray | None = None

    def search(
        self,
        query: str,
        k: int = 10,
        expand: bool = True,
        min_confidence: float = 0.5,
        *,
        bm25: bool = True,
        docs: bool = False,
    ) -> list[SearchHit]:
        """Search the code, or with `docs=True` the documentation sections (D-42).

        The two are never mixed in one list. `bm25=False` is for the evaluation, to
        measure vectors alone.
        """
        self.notes = []
        nodes: dict[str, Node] = {}
        bm25 = self._bm25(query, nodes, docs) if bm25 else []
        vector = self._vector(query, nodes, docs)
        fused = rrf([[n for n in bm25], [n for n in vector]])
        sources = {i: [s for s, lst in (("bm25", bm25), ("vector", vector)) if i in lst]
                   for i in fused}
        ranked = sorted(fused, key=lambda i: (-fused[i], i))
        hits = [SearchHit(nodes[i], fused[i], sources[i]) for i in ranked[:k]]
        if expand and not docs:  # a section's only neighbour is its own file
            # Neighbours compete with the fused hits for the k places: appended after the
            # top k, they could never change what the agent reads first.
            hits.extend(self._expand(hits, min_confidence))
            hits = sorted(hits, key=lambda h: (-h.score, h.node.id))[:k]
        return hits

    def _bm25(self, query: str, nodes: dict[str, Node], docs: bool) -> list[str]:
        found = self.store.search_text(self.snapshot_id, query, POOL, docs=docs)
        for node, _ in found:
            nodes[node.id] = node
        return [node.id for node, _ in found]

    def _vector(self, query: str, nodes: dict[str, Node], docs: bool) -> list[str]:
        if self.embedder is None:
            self.notes.append("no embedder given: BM25 only")
            return []
        if self._ids is None:
            self._ids, self._matrix = self.store.embeddings(self.snapshot_id, self.embedder.model)
        if not self._ids or self._matrix is None:
            self.notes.append("no embeddings for this snapshot: BM25 only")
            return []
        try:
            q = np.asarray(self.embedder.embed([query])[0], dtype=np.float32)
        except Exception as exc:  # the model cannot be loaded or downloaded here
            self.notes.append(f"embedding model unavailable ({exc}): BM25 only")
            return []
        norm = float(np.linalg.norm(q))
        if norm > 0:
            q = q / norm
        if self._norms is None:  # computed once per snapshot, not per query
            self._norms = np.linalg.norm(self._matrix, axis=1)
            self._norms[self._norms == 0] = 1.0
        sims = (self._matrix @ q) / self._norms
        # Rows of the other search (sections, or code) can never be candidates.
        wanted = np.fromiter(((SECTION_MARK in i) == docs for i in self._ids), bool, len(sims))
        if not wanted.any():
            return []
        sims = np.where(wanted, sims, -np.inf)
        # Take a candidate pool with argpartition (linear time), then order only that pool.
        # Stable order: ties break by node id so results never depend on row order.
        pool = min(POOL, int(wanted.sum()))
        candidates = np.argpartition(-sims, pool - 1)[:pool]
        order = sorted(candidates.tolist(), key=lambda i: (-float(sims[i]), self._ids[i]))
        top = [self._ids[i] for i in order]
        for node_id in top:
            if node_id not in nodes:
                node = self.store.node(node_id)
                if node is not None:
                    nodes[node_id] = node
        return [i for i in top if i in nodes]

    def _expand(self, hits: list[SearchHit], min_confidence: float) -> list[SearchHit]:
        present = {h.node.id for h in hits}
        added: dict[str, SearchHit] = {}
        for hit in hits:
            edges = self.store.edges_from(hit.node.id, EXPAND_KINDS, min_confidence)
            edges += self.store.edges_to(hit.node.id, EXPAND_KINDS, min_confidence)
            for edge in edges:
                other = edge.dst_id if edge.src_id == hit.node.id else edge.src_id
                if other in present:
                    continue
                node = self.store.node(other)
                if node is None or not node.path or node.kind is NodeKind.EXTERNAL:
                    continue  # an external symbol has no lines to show
                if node.kind is NodeKind.SECTION:
                    continue  # documentation is its own search
                score = hit.score * edge.confidence * GRAPH_DISCOUNT
                old = added.get(other)
                if old is None or score > old.score:
                    added[other] = SearchHit(node, score, ["graph"], edge)
        return sorted(added.values(), key=lambda h: (-h.score, h.node.id))


def context_pack(hits: list[SearchHit], max_lines: int = 200) -> list[ContextSpan]:
    """`path:start-end` spans in score order, merged when they overlap, cut at `max_lines`."""
    spans: list[ContextSpan] = []
    for hit in sorted(hits, key=lambda h: (-h.score, h.node.id)):
        room = max_lines - sum(s.lines for s in spans)
        n = hit.node
        new = ContextSpan(n.path, n.span.start_line, n.span.end_line, _reason(hit))
        overlap = next((s for s in spans if s.overlaps(new)), None)
        if overlap is not None:
            room += overlap.lines  # merging replaces it
            new = overlap.merged(new)
        if room <= 0:
            continue
        new.end_line = min(new.end_line, new.start_line + room - 1)
        if overlap is not None:
            spans[spans.index(overlap)] = new
        else:
            spans.append(new)
    return spans


@dataclass(slots=True)
class ContextSpan:
    """A file range for the model to read, with a one-line reason."""

    path: str
    start_line: int
    end_line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"

    @property
    def lines(self) -> int:
        return self.end_line - self.start_line + 1

    def overlaps(self, other: ContextSpan) -> bool:
        return (self.path == other.path and self.start_line <= other.end_line
                and other.start_line <= self.end_line)

    def merged(self, other: ContextSpan) -> ContextSpan:
        return ContextSpan(self.path, min(self.start_line, other.start_line),
                           max(self.end_line, other.end_line), f"{self.reason}; {other.reason}")

    @property
    def span(self) -> Span:
        return Span(self.start_line, self.end_line)


def _reason(hit: SearchHit) -> str:
    n = hit.node
    label = n.qualname or n.path
    if hit.via is not None:
        return f"{label} ({hit.via.kind} neighbour)"
    return f"{label} (found by {' + '.join(hit.sources)})"
