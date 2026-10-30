"""Record-and-replay cache for chat calls, and a vector cache for embeddings.

Both live in one SQLite file so an evaluation can be re-run offline from a single
artefact. Chat keys are provider-independent: the same request answered by Groq today
replays tomorrow even if Groq is down.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from codeatlas.llm.types import LLMResponse, Message, ToolSpec

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_cache (
    key TEXT PRIMARY KEY,
    response TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS embedding_cache (
    model TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (model, text_hash)
);
"""


def canonical_json(value: Any) -> str:
    """JSON with sorted keys and no whitespace, so equal data always gives equal text."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_payload(
    messages: Sequence[Message],
    tools: Sequence[ToolSpec] | None,
    temperature: float,
    max_tokens: int | None,
    namespace: str,
) -> dict[str, Any]:
    """The parts of a request that decide its answer, without any provider detail."""
    return {
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "tool_call_id": m.tool_call_id,
                # Signatures are opaque provider data and change on every live run.
                "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments}
                               for c in m.tool_calls],
            }
            for m in messages
        ],
        "tools": [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in tools or ()
        ],
        "temperature": float(temperature),
        "max_tokens": max_tokens,
        "cache_namespace": namespace,
    }


def cache_key(
    messages: Sequence[Message],
    tools: Sequence[ToolSpec] | None,
    temperature: float,
    max_tokens: int | None,
    namespace: str,
) -> str:
    """SHA-256 of the canonical request JSON."""
    payload = request_payload(messages, tools, temperature, max_tokens, namespace)
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class LLMCache:
    """SQLite-backed store for chat responses and embedding vectors."""

    def __init__(self, path: Path) -> None:
        self.path = path
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.executescript(_SCHEMA)

    def get_chat(self, key: str) -> LLMResponse | None:
        row = self._db.execute("SELECT response FROM chat_cache WHERE key = ?", (key,)).fetchone()
        return None if row is None else LLMResponse.from_dict(json.loads(row[0]), cached=True)

    def put_chat(self, key: str, response: LLMResponse) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO chat_cache (key, response, created) VALUES (?, ?, ?)",
                (key, canonical_json(response.to_dict()), time.time()),
            )

    def get_vectors(self, model: str, hashes: Sequence[str]) -> dict[str, np.ndarray]:
        """Cached float32 vectors for the given text hashes; missing ones are absent."""
        found: dict[str, np.ndarray] = {}
        unique = list(dict.fromkeys(hashes))
        for start in range(0, len(unique), 500):  # stay under SQLite's variable limit
            chunk = unique[start : start + 500]
            marks = ",".join("?" * len(chunk))
            rows = self._db.execute(
                f"SELECT text_hash, vector FROM embedding_cache "
                f"WHERE model = ? AND text_hash IN ({marks})",
                (model, *chunk),
            )
            for digest, blob in rows:
                found[digest] = np.frombuffer(blob, dtype=np.float32)
        return found

    def put_vectors(self, model: str, vectors: dict[str, np.ndarray]) -> None:
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO embedding_cache (model, text_hash, vector) "
                "VALUES (?, ?, ?)",
                [(model, h, v.astype(np.float32).tobytes()) for h, v in vectors.items()],
            )

    def close(self) -> None:
        self._db.close()
