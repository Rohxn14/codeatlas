# T03: Graph store

**Wave**: 1 (parallel with T01, T02, T04, T05)
**Branch**: `task/T03-store`

## Goal

One SQLite file holds every snapshot's files, nodes, edges, unresolved calls, a full-text index and embeddings. A NetworkX view built from it answers graph traversals. The store also implements the contract's `SymbolIndex`, so resolvers and linkers can look symbols up.

## Files you may create or edit

- `src/codeatlas/store/` (any modules inside it)
- `tests/store/`
- `docs/explainers/store.md`

## Schema (v1)

| Table | Columns (main ones) | Notes |
| --- | --- | --- |
| `snapshots` | id, repo, commit_sha, indexed_at, indexer_version | |
| `files` | snapshot_id, path, language, tier, sha256, size_bytes | Primary key (snapshot_id, path) |
| `nodes` | id, key, snapshot_id, kind, language, name, qualname, path, start_line, end_line, start_col, end_col, signature, docstring, owner_key, attrs_json | Indexes on (snapshot_id, key), (snapshot_id, name), (snapshot_id, path) |
| `edges` | snapshot_id, src_id, dst_id, kind, confidence, resolution, line, attrs_json | Indexes on (snapshot_id, src_id, kind) and (snapshot_id, dst_id, kind) |
| `raw_calls` | snapshot_id, caller_key, callee_text, name, receiver, line, resolved (0/1) | Lets the eval count what stayed unresolved |
| `nodes_fts` | FTS5 over name, qualname, signature, docstring, path | External-content table tied to `nodes` |
| `embeddings` | node_id, model, dim, vector (float32 blob) | Written by T08 later; create the table now |
| `meta` | key, value | Schema version |

## API

A `GraphStore` class, constructed with a database path (`:memory:` allowed):

| Method | Purpose |
| --- | --- |
| `create_snapshot(snapshot)`, `get_snapshot(id)`, `latest_snapshot(repo)` | Snapshots |
| `write_files`, `write_nodes`, `write_edges`, `write_raw_calls` | Bulk inserts inside one transaction |
| `file_hashes(snapshot_id) -> dict[path, sha256]` | For incremental re-index |
| `copy_unchanged(from_snapshot, to_snapshot, paths)` | Copies nodes for unchanged files into the new snapshot, rewriting ids; edges are recomputed by the pipeline later |
| `node(id)`, `nodes_by_key`, `nodes_by_name`, `nodes_in_file` | Lookups |
| `edges_from(id, kinds=None)`, `edges_to(id, kinds=None)` | One hop, with optional kinds and minimum confidence |
| `search_text(snapshot_id, query, k)` | BM25 ranking over `nodes_fts` |
| `symbol_index(snapshot_id) -> SymbolIndex` | An object implementing the contract protocol |
| `graph(snapshot_id, kinds=None, min_confidence=0.0) -> networkx.MultiDiGraph` | Edge attributes: kind, confidence, resolution, line |
| `export_json(snapshot_id) -> dict` | The format in contract section 8 |

Traversal helpers in `store/graph.py`, operating on the NetworkX view:

| Function | Purpose |
| --- | --- |
| `callers(g, node_id, depth, min_confidence)` | Reverse walk over CALLS |
| `callees(g, node_id, depth, min_confidence)` | Forward walk over CALLS |
| `reverse_reach(g, node_ids, kinds, depth)` | All nodes that reach any of the given nodes, with the best path confidence (product of edge confidences); used later by the impact engine |

## Design notes

- `attrs` is stored as JSON text; convert back to `dict` when reading.
- Check that FTS5 is available at startup; if not, raise a clear error naming the SQLite version. Python's bundled SQLite on Windows and Linux normally includes it.
- Use `executemany` and one transaction per bulk write; indexing a medium repo writes tens of thousands of rows.
- The schema version lives in `meta`; a mismatch raises an error telling the user to re-index.

## Tests

Round-trip every data class through the store; FTS ranking puts an exact name match first; `copy_unchanged` rewrites ids and keeps keys; `reverse_reach` returns best-path confidence on a small hand-built graph with two paths of different confidence; `symbol_index` passes an `isinstance(..., SymbolIndex)` check; `export_json` matches the contract shape.

## Done when

All tests pass on Linux and Windows CI; explainer written, including the schema as a table and why SQLite was chosen over a graph database.
