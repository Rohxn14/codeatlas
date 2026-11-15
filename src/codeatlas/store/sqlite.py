"""GraphStore: every snapshot's files, nodes, edges and raw calls in one SQLite file."""

import json
import re
import sqlite3
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path

import networkx as nx
import numpy as np

from codeatlas.models import (
    Edge,
    EdgeKind,
    FileRecord,
    Node,
    NodeKind,
    RawCall,
    Resolution,
    Snapshot,
    Span,
    Tier,
)
from codeatlas.store.schema import ensure_fts5, init_schema
from codeatlas.store.symbols import StoreSymbolIndex

_NODE_COLUMNS = (
    "id, key, snapshot_id, kind, language, name, qualname, path, start_line, end_line, "
    "start_col, end_col, signature, docstring, owner_key, attrs_json"
)
# bm25 weights, in nodes_fts column order: name, qualname, signature, docstring, path.
_BM25_WEIGHTS = "10.0, 5.0, 2.0, 1.0, 1.0"
_WORD = re.compile(r"\w+")


class GraphStore:
    """Reads and writes the code graph; one instance per database file."""

    def __init__(self, path: str | Path) -> None:
        ensure_fts5()
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        try:
            init_schema(self._conn)
        except Exception:
            # An open connection keeps the file locked on Windows, which would block the
            # "delete the database and re-index" advice the schema check gives.
            self._conn.close()
            raise
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "GraphStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # Snapshots

    def create_snapshot(self, snapshot: Snapshot) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot.id,
                    snapshot.repo,
                    snapshot.commit_sha,
                    snapshot.indexed_at,
                    snapshot.indexer_version,
                    snapshot.source,
                    json.dumps(list(snapshot.limits_hit)),
                ),
            )

    def get_snapshot(self, snapshot_id: str) -> Snapshot | None:
        row = self._conn.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        return _snapshot(row) if row else None

    def latest_snapshot(self, repo: str) -> Snapshot | None:
        """The most recently indexed snapshot of a repo (ISO 8601 UTC sorts as text)."""
        row = self._conn.execute(
            "SELECT * FROM snapshots WHERE repo = ? ORDER BY indexed_at DESC, rowid DESC LIMIT 1",
            (repo,),
        ).fetchone()
        return _snapshot(row) if row else None

    def snapshots(self) -> list[Snapshot]:
        """Every snapshot in the database, newest first: what the web app lists."""
        rows = self._conn.execute("SELECT * FROM snapshots ORDER BY indexed_at DESC, rowid DESC")
        return [_snapshot(row) for row in rows]

    def delete_snapshot(self, snapshot_id: str) -> int:
        """Remove a snapshot and everything in it, so the same commit can be indexed again.

        Returns the number of nodes removed. The FTS delete trigger keeps search in step.
        """
        prefix = snapshot_id + "/"
        with self._conn:
            removed = self._conn.execute(
                "DELETE FROM nodes WHERE snapshot_id = ?", (snapshot_id,)
            ).rowcount
            for table in ("files", "edges", "raw_calls"):
                self._conn.execute(f"DELETE FROM {table} WHERE snapshot_id = ?", (snapshot_id,))
            self._conn.execute(
                "DELETE FROM embeddings WHERE substr(node_id, 1, ?) = ?",
                (len(prefix), prefix),
            )
            self._conn.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
        return removed

    def _require_snapshot(self, snapshot_id: str) -> None:
        """Writes for an unknown snapshot would succeed and then be invisible to lookups."""
        if self.get_snapshot(snapshot_id) is None:
            raise KeyError(f"no snapshot {snapshot_id!r}: call create_snapshot first")

    # Bulk writes: one transaction and one executemany each

    def write_files(self, snapshot_id: str, files: Iterable[FileRecord]) -> int:
        self._require_snapshot(snapshot_id)
        rows = [
            (snapshot_id, f.path, f.language, str(f.tier), f.sha256, f.size_bytes) for f in files
        ]
        with self._conn:
            self._conn.executemany("INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)", rows)
        return len(rows)

    def write_nodes(self, nodes: Iterable[Node]) -> int:
        """Insert nodes; a repeated id is an error, since it would hide a symbol."""
        nodes = list(nodes)
        for snapshot_id in {n.snapshot_id for n in nodes}:
            self._require_snapshot(snapshot_id)
        rows = [_node_row(n) for n in nodes]
        counts = Counter(row[0] for row in rows)
        repeated = sorted(node_id for node_id, count in counts.items() if count > 1)
        if repeated:
            raise ValueError(f"duplicate node ids in one write: {repeated[:5]}")
        with self._conn:
            self._conn.executemany(
                f"INSERT INTO nodes ({_NODE_COLUMNS}) VALUES ({', '.join('?' * 16)})", rows
            )
        return len(rows)

    def write_edges(self, snapshot_id: str, edges: Iterable[Edge]) -> int:
        self._require_snapshot(snapshot_id)
        rows = [
            (
                snapshot_id,
                e.src_id,
                e.dst_id,
                str(e.kind),
                e.confidence,
                str(e.resolution),
                e.line,
                json.dumps(e.attrs),
            )
            for e in edges
        ]
        with self._conn:
            self._conn.executemany("INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        return len(rows)

    def write_raw_calls(
        self, snapshot_id: str, calls: Iterable[RawCall], resolved: bool = False
    ) -> int:
        self._require_snapshot(snapshot_id)
        rows = [
            (snapshot_id, c.caller_key, c.callee_text, c.name, c.receiver, c.line, int(resolved))
            for c in calls
        ]
        with self._conn:
            self._conn.executemany("INSERT INTO raw_calls VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        return len(rows)

    def mark_resolved_calls(self, snapshot_id: str) -> int:
        """Flag raw calls that a CALLS edge now covers.

        Resolvers return edges, not which raw calls they used, so this matches them
        afterwards; the eval counts the rest as unresolved. A raw call is covered when
        its caller has a CALLS edge to a node with the same name (on any line, since a
        repeated call keeps one edge at its first line), or, for a constructor call
        such as `Foo()` resolved to `Foo.__init__`, an edge on the same line to an
        `__init__` or `constructor`. Matching on the line alone would mark `mystery`
        resolved in `foo(mystery())` when only `foo` was.
        """
        prefix = snapshot_id + "/"
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE raw_calls SET resolved = 1
                WHERE snapshot_id = ? AND resolved = 0 AND EXISTS (
                    SELECT 1 FROM edges e JOIN nodes n ON n.id = e.dst_id
                    WHERE e.snapshot_id = raw_calls.snapshot_id AND e.kind = ?
                      AND e.src_id = ? || raw_calls.caller_key
                      AND (n.name = raw_calls.name OR (
                           e.line = raw_calls.line AND n.name IN ('__init__', 'constructor')))
                )
                """,
                (snapshot_id, str(EdgeKind.CALLS), prefix),
            )
        return cursor.rowcount

    def raw_calls(
        self, snapshot_id: str, resolved: bool | None = None
    ) -> list[tuple[RawCall, bool]]:
        sql = "SELECT * FROM raw_calls WHERE snapshot_id = ?"
        params: list[object] = [snapshot_id]
        if resolved is not None:
            sql += " AND resolved = ?"
            params.append(int(resolved))
        rows = self._conn.execute(sql + " ORDER BY rowid", params).fetchall()
        return [
            (
                RawCall(r["caller_key"], r["callee_text"], r["name"], r["receiver"], r["line"]),
                bool(r["resolved"]),
            )
            for r in rows
        ]

    # Incremental re-index

    def file_hashes(self, snapshot_id: str) -> dict[str, str]:
        rows = self._conn.execute(
            "SELECT path, sha256 FROM files WHERE snapshot_id = ?", (snapshot_id,)
        )
        return {r["path"]: r["sha256"] for r in rows}

    def files(self, snapshot_id: str) -> list[FileRecord]:
        rows = self._conn.execute(
            "SELECT * FROM files WHERE snapshot_id = ? ORDER BY path", (snapshot_id,)
        )
        return [
            FileRecord(r["path"], r["language"], Tier(r["tier"]), r["sha256"], r["size_bytes"])
            for r in rows
        ]

    def copy_unchanged(self, from_snapshot: str, to_snapshot: str, paths: Iterable[str]) -> int:
        """Copy the nodes of unchanged files into a new snapshot under new ids.

        Keys stay the same, so the impact engine can still match symbols across
        snapshots. Edges are not copied: their targets may live in changed files.
        """
        with self._conn:
            self._conn.execute("CREATE TEMP TABLE IF NOT EXISTS copy_paths (path TEXT PRIMARY KEY)")
            self._conn.execute("DELETE FROM copy_paths")
            self._conn.executemany(
                "INSERT OR IGNORE INTO copy_paths VALUES (?)", ((p,) for p in paths)
            )
            cursor = self._conn.execute(
                f"""
                INSERT INTO nodes ({_NODE_COLUMNS})
                SELECT ? || '/' || key, key, ?, kind, language, name, qualname, path,
                       start_line, end_line, start_col, end_col, signature, docstring,
                       owner_key, attrs_json
                FROM nodes
                WHERE snapshot_id = ? AND path IN (SELECT path FROM copy_paths)
                ORDER BY pk
                """,
                (to_snapshot, to_snapshot, from_snapshot),
            )
            self._conn.execute("DELETE FROM copy_paths")
        return cursor.rowcount

    # Node lookups

    def node(self, node_id: str) -> Node | None:
        row = self._conn.execute(
            f"SELECT {_NODE_COLUMNS} FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        return _node(row) if row else None

    def nodes(self, snapshot_id: str) -> list[Node]:
        return self._select_nodes("snapshot_id = ?", (snapshot_id,))

    def nodes_by_key(self, key: str, snapshot_id: str | None = None) -> list[Node]:
        """The node with this key in one snapshot, or in every snapshot when none is given."""
        if snapshot_id is None:
            return self._select_nodes("key = ?", (key,))
        return self._select_nodes("snapshot_id = ? AND key = ?", (snapshot_id, key))

    def nodes_by_name(
        self, snapshot_id: str, name: str, language: str | None = None
    ) -> list[Node]:
        if language is None:
            return self._select_nodes("snapshot_id = ? AND name = ?", (snapshot_id, name))
        return self._select_nodes(
            "snapshot_id = ? AND name = ? AND language = ?", (snapshot_id, name, language)
        )

    def nodes_in_file(self, snapshot_id: str, path: str) -> list[Node]:
        return self._select_nodes(
            "snapshot_id = ? AND path = ?", (snapshot_id, path), "start_line, pk"
        )

    def members(self, snapshot_id: str, owner_key: str) -> list[Node]:
        return self._select_nodes(
            "snapshot_id = ? AND owner_key = ?", (snapshot_id, owner_key), "start_line, pk"
        )

    def module_for_path(self, snapshot_id: str, path: str) -> Node | None:
        found = self._select_nodes(
            "snapshot_id = ? AND path = ? AND kind = ?", (snapshot_id, path, str(NodeKind.MODULE))
        )
        return found[0] if found else None

    def _select_nodes(self, where: str, params: Sequence[object], order: str = "pk") -> list[Node]:
        rows = self._conn.execute(
            f"SELECT {_NODE_COLUMNS} FROM nodes WHERE {where} ORDER BY {order}", params
        )
        return [_node(r) for r in rows]

    # Edge lookups

    def edges_from(
        self,
        node_id: str,
        kinds: Iterable[EdgeKind] | None = None,
        min_confidence: float = 0.0,
    ) -> list[Edge]:
        return self._edges("src_id", node_id, kinds, min_confidence)

    def edges_to(
        self,
        node_id: str,
        kinds: Iterable[EdgeKind] | None = None,
        min_confidence: float = 0.0,
    ) -> list[Edge]:
        return self._edges("dst_id", node_id, kinds, min_confidence)

    def edges(self, snapshot_id: str) -> list[Edge]:
        rows = self._conn.execute(
            "SELECT * FROM edges WHERE snapshot_id = ? ORDER BY rowid", (snapshot_id,)
        )
        return [_edge(r) for r in rows]

    def _edges(
        self,
        column: str,
        node_id: str,
        kinds: Iterable[EdgeKind] | None,
        min_confidence: float,
    ) -> list[Edge]:
        snapshot_id = self._snapshot_of(node_id)
        if snapshot_id is None:
            return []
        sql = f"SELECT * FROM edges WHERE snapshot_id = ? AND {column} = ? AND confidence >= ?"
        params: list[object] = [snapshot_id, node_id, min_confidence]
        if kinds is not None:
            kind_list = [str(k) for k in kinds]
            sql += f" AND kind IN ({', '.join('?' * len(kind_list))})"
            params.extend(kind_list)
        return [_edge(r) for r in self._conn.execute(sql + " ORDER BY rowid", params)]

    def _snapshot_of(self, node_id: str) -> str | None:
        """The snapshot a node id belongs to, found by its `{snapshot_id}/` prefix.

        Splitting on the first slash would break for repo names that contain one, and
        edge endpoints need not have a node row, so the snapshots table decides.
        """
        row = self._conn.execute(
            "SELECT id FROM snapshots WHERE substr(?, 1, length(id) + 1) = id || '/' "
            "ORDER BY length(id) DESC LIMIT 1",
            (node_id,),
        ).fetchone()
        return row["id"] if row else None

    # Search

    def search_text(self, snapshot_id: str, query: str, k: int = 10) -> list[tuple[Node, float]]:
        """BM25 search over names, signatures, docstrings and paths; higher score is better.

        Each word of the query is quoted, so FTS5 syntax characters in user input are
        harmless, and the words are OR-ed so a partial match still ranks. A node whose
        name equals the query is put first, whatever its BM25 score.
        """
        words = _WORD.findall(query)
        if not words or k <= 0:
            return []
        match = " OR ".join(f'"{w}"' for w in words)
        rows = self._conn.execute(
            f"""
            SELECT {", ".join("n." + c for c in _NODE_COLUMNS.split(", "))},
                   bm25(nodes_fts, {_BM25_WEIGHTS}) AS rank
            FROM nodes_fts JOIN nodes n ON n.pk = nodes_fts.rowid
            WHERE nodes_fts MATCH ? AND n.snapshot_id = ?
            ORDER BY rank
            LIMIT ?
            """,
            (match, snapshot_id, max(k * 5, 50)),
        ).fetchall()
        wanted = query.strip().lower()
        hits = [(_node(r), -r["rank"]) for r in rows]
        hits.sort(key=lambda hit: (hit[0].name.lower() != wanted, -hit[1]))
        return hits[:k]

    # Embeddings

    def write_embeddings(self, rows: Iterable[tuple[str, str, np.ndarray]]) -> int:
        """Store `(node_id, model, vector)` rows as float32 blobs; a repeat replaces the old."""
        data = []
        for node_id, model, vector in rows:
            vec = np.asarray(vector, dtype=np.float32).ravel()
            data.append((node_id, model, int(vec.size), vec.tobytes()))
        with self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO embeddings (node_id, model, dim, vector) "
                "VALUES (?, ?, ?, ?)",
                data,
            )
        return len(data)

    def embeddings(self, snapshot_id: str, model: str) -> tuple[list[str], np.ndarray]:
        """Node ids and a `(n, dim)` float32 matrix for one snapshot and model.

        Empty snapshots give `([], zeros((0, 0)))` so callers can test `len(ids)`.
        """
        rows = self._conn.execute(
            "SELECT node_id, dim, vector FROM embeddings "
            "WHERE model = ? AND substr(node_id, 1, ?) = ? ORDER BY node_id",
            (model, len(snapshot_id) + 1, snapshot_id + "/"),
        ).fetchall()
        if not rows:
            return [], np.zeros((0, 0), dtype=np.float32)
        ids = [r["node_id"] for r in rows]
        matrix = np.stack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
        return ids, matrix

    # Views

    def symbol_index(self, snapshot_id: str) -> StoreSymbolIndex:
        return StoreSymbolIndex(self, snapshot_id)

    def graph(
        self,
        snapshot_id: str,
        kinds: Iterable[EdgeKind] | None = None,
        min_confidence: float = 0.0,
    ) -> nx.MultiDiGraph:
        """A NetworkX view of one snapshot, for traversals the SQL lookups make awkward."""
        g = nx.MultiDiGraph(snapshot_id=snapshot_id)
        # Straight from the columns: building full Node and Edge objects first took about
        # twice as long on a 50,000-node graph.
        node_rows = self._conn.execute(
            "SELECT id, key, kind, name, path, language FROM nodes WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        g.add_nodes_from(
            (r["id"], {"key": r["key"], "kind": NodeKind(r["kind"]), "name": r["name"],
                       "path": r["path"], "language": r["language"]})
            for r in node_rows
        )
        sql = (
            "SELECT src_id, dst_id, kind, confidence, resolution, line FROM edges "
            "WHERE snapshot_id = ? AND confidence >= ?"
        )
        params: list[object] = [snapshot_id, min_confidence]
        if kinds is not None:
            kind_list = [str(k) for k in kinds]
            sql += f" AND kind IN ({', '.join('?' * len(kind_list))})"
            params.extend(kind_list)
        g.add_edges_from(
            (r["src_id"], r["dst_id"], {"kind": EdgeKind(r["kind"]),
                                        "confidence": r["confidence"],
                                        "resolution": Resolution(r["resolution"]),
                                        "line": r["line"]})
            for r in self._conn.execute(sql + " ORDER BY rowid", params)
        )
        return g

    def export_json(self, snapshot_id: str) -> dict[str, object]:
        """The graph in the shape of contract section 8, compared by key, not id."""
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot is None:
            raise KeyError(f"no snapshot {snapshot_id!r}")
        nodes = self.nodes(snapshot_id)
        key_of = {n.id: n.key for n in nodes}
        prefix = snapshot_id + "/"

        def key(node_id: str) -> str:
            return key_of.get(node_id, node_id.removeprefix(prefix))

        return {
            "snapshot": {
                "id": snapshot.id,
                "repo": snapshot.repo,
                "commit_sha": snapshot.commit_sha,
                "indexed_at": snapshot.indexed_at,
                "indexer_version": snapshot.indexer_version,
                "source": snapshot.source,
                "limits_hit": list(snapshot.limits_hit),
            },
            "nodes": [
                {
                    "key": n.key,
                    "kind": str(n.kind),
                    "language": n.language,
                    "path": n.path,
                    "span": {"start_line": n.span.start_line, "end_line": n.span.end_line},
                }
                for n in nodes
            ],
            "edges": [
                {
                    "src_key": key(e.src_id),
                    "dst_key": key(e.dst_id),
                    "kind": str(e.kind),
                    "confidence": e.confidence,
                    "resolution": str(e.resolution),
                    "line": e.line,
                }
                for e in self.edges(snapshot_id)
            ],
        }


# Row conversion


def _snapshot(row: sqlite3.Row) -> Snapshot:
    return Snapshot(
        id=row["id"],
        repo=row["repo"],
        commit_sha=row["commit_sha"],
        indexed_at=row["indexed_at"],
        indexer_version=row["indexer_version"],
        source=row["source"],
        limits_hit=tuple(json.loads(row["limits_hit_json"])),
    )


def _node_row(n: Node) -> tuple[object, ...]:
    return (
        n.id,
        n.key,
        n.snapshot_id,
        str(n.kind),
        n.language,
        n.name,
        n.qualname,
        n.path,
        n.span.start_line,
        n.span.end_line,
        n.span.start_col,
        n.span.end_col,
        n.signature,
        n.docstring,
        n.owner_key,
        json.dumps(n.attrs),
    )


def _node(row: sqlite3.Row) -> Node:
    return Node(
        id=row["id"],
        key=row["key"],
        snapshot_id=row["snapshot_id"],
        kind=NodeKind(row["kind"]),
        language=row["language"],
        name=row["name"],
        qualname=row["qualname"],
        path=row["path"],
        span=Span(row["start_line"], row["end_line"], row["start_col"], row["end_col"]),
        signature=row["signature"],
        docstring=row["docstring"],
        owner_key=row["owner_key"],
        attrs=json.loads(row["attrs_json"]),
    )


def _edge(row: sqlite3.Row) -> Edge:
    return Edge(
        src_id=row["src_id"],
        dst_id=row["dst_id"],
        kind=EdgeKind(row["kind"]),
        confidence=row["confidence"],
        resolution=Resolution(row["resolution"]),
        line=row["line"],
        attrs=json.loads(row["attrs_json"]),
    )
