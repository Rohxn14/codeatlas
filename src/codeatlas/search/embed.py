"""Build the symbol embeddings that vector search reads."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np

from codeatlas.models import Node, NodeKind
from codeatlas.store import GraphStore

EMBEDDED_KINDS = frozenset({
    NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.INTERFACE, NodeKind.TEST, NodeKind.MODULE,
    NodeKind.SECTION,
})
BODY_LINES = 15
BATCH = 64


class Embedder(Protocol):
    """What search needs from T04's `EmbeddingClient`; tests pass a fake with the same shape."""

    model: str

    def embed(self, texts: list[str]) -> np.ndarray: ...


def node_text(node: Node, repo_root: Path | None = None) -> str:
    """Words that describe a symbol: the part of it a question could match.

    The body is optional because a store can outlive the checkout it was built from.
    """
    parts = [f"{node.kind} {node.qualname or node.path}", f"path: {node.path}"]
    if node.signature:
        parts.append(node.signature)
    if node.docstring:
        parts.append(node.docstring)
    # A section's docstring already is its text; the body would repeat it.
    if repo_root is not None and node.kind is not NodeKind.SECTION:
        body = _body(node, repo_root)
        if body:
            parts.append(body)
    return "\n".join(parts)


def _body(node: Node, repo_root: Path) -> str:
    try:
        raw = (repo_root / node.path).read_bytes()
    except OSError:
        return ""
    lines = raw.decode("utf-8", errors="replace").splitlines()
    start = max(node.span.start_line - 1, 0)
    end = min(node.span.end_line, start + BODY_LINES)
    return "\n".join(lines[start:end])


def build_embeddings(
    store: GraphStore,
    snapshot_id: str,
    embedder: Embedder,
    repo_root: Path | None = None,
) -> int:
    """Embed the snapshot's symbols that lack a vector for this model; returns how many.

    Re-running only pays for new nodes, so a second call after an unchanged index is free.
    Symbols go in order of text length: the model pads every text of a batch to the
    batch's longest, so in file order one long docstring made 63 short signatures cost
    as much as it did. On PitwallOS's 2,022 symbols: 195 s in file order, about 50 s by
    length (Nov 19), with the same vectors.
    """
    done, _ = store.embeddings(snapshot_id, embedder.model)
    have = set(done)
    todo = [(node_text(n, repo_root), n) for n in store.nodes(snapshot_id)
            if n.kind in EMBEDDED_KINDS and n.id not in have]
    todo.sort(key=lambda item: len(item[0]))
    for start in range(0, len(todo), BATCH):
        batch = todo[start : start + BATCH]
        vectors = embedder.embed([text for text, _ in batch])
        store.write_embeddings(
            (n.id, embedder.model, v) for (_, n), v in zip(batch, vectors, strict=True)
        )
    return len(todo)
