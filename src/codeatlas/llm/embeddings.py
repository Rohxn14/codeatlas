"""Local text embeddings with `fastembed`, cached by (model, text hash).

Embeddings run on this machine, so they cost time rather than credit; the cache exists
so re-indexing an unchanged repository does not re-embed every symbol.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

import numpy as np

from codeatlas.llm.cache import LLMCache, text_hash
from codeatlas.llm.config import LLMConfig, load_llm_config

# Takes a batch of texts, returns one vector per text (any float dtype).
Embedder = Callable[[list[str]], Iterable[np.ndarray]]


class EmbeddingClient:
    """`embed(texts)` returns float32 rows of unit length, in the order given."""

    def __init__(
        self,
        model: str = "BAAI/bge-small-en-v1.5",
        cache: LLMCache | None = None,
        batch_size: int = 64,
        embedder: Embedder | None = None,
    ) -> None:
        self.model = model
        self.cache = cache
        self.batch_size = batch_size
        self._embedder = embedder

    @classmethod
    def from_config(cls, config: LLMConfig | None = None) -> EmbeddingClient:
        config = config or load_llm_config()
        cache = None if config.cache == "off" else LLMCache(config.cache_path)
        return cls(config.embedding_model, cache, config.embedding_batch_size)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        hashes = [text_hash(t) for t in texts]
        known = self.cache.get_vectors(self.model, hashes) if self.cache else {}
        missing = {h: t for h, t in zip(hashes, texts, strict=True) if h not in known}
        fresh = self._embed_missing(list(missing.values()))
        new = dict(zip(missing, fresh, strict=True))
        if self.cache is not None and new:
            self.cache.put_vectors(self.model, new)
        known.update(new)
        return np.stack([known[h] for h in hashes]).astype(np.float32)

    def _embed_missing(self, texts: list[str]) -> list[np.ndarray]:
        vectors: list[np.ndarray] = []
        embedder = self._get_embedder() if texts else None
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            vectors.extend(_normalise(np.asarray(v, dtype=np.float32)) for v in embedder(batch))
        return vectors

    def _get_embedder(self) -> Embedder:
        """Load the model on first use: it downloads weights and takes seconds."""
        if self._embedder is None:
            from fastembed import TextEmbedding

            model = TextEmbedding(self.model)
            self._embedder = lambda batch: model.embed(batch, batch_size=len(batch))
        return self._embedder


def _normalise(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else vector
