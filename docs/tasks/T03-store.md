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

## Review of PR #5 (Oct 30)

**Verdict**: merge after fixes (one small must fix). **Fixes**: issue #12. Paste it into the T03 session, wait for CI, then merge.

**What the PR does**: `GraphStore`, one SQLite file holding snapshots, files, nodes, edges and raw calls, with an FTS5 index kept in sync by triggers and an empty embeddings table ready for T08. On top: bulk writes, lookups, BM25 search, `copy_unchanged`, `StoreSymbolIndex`, a NetworkX view and `export_json`. `store/graph.py` adds `callers`, `callees` and `reverse_reach` (best path confidence, the product of edge confidences, with an optional depth limit).

| Check | Result | Evidence |
| --- | --- | --- |
| Scope | PASS | 8 files, all inside the brief |
| Contract untouched | PASS | No diff in `models.py` or `indexer/adapter.py` |
| Tests | PASS | 168 passed; 24 for the store |
| Lint | PASS | `ruff check .` clean |
| Mutation spot-check | PASS, one survivor | 5 caught; using live scores instead of the start-of-round snapshot (`graph.py:63`) survives |
| Explainer | PASS | Schema table, SQLite vs graph database, a worked traversal |
| Brief coverage | PASS | Every API row and test is present |
| Safety | PASS | No subprocess, exec, eval or importlib |
| Silent gaps | WARN | Writes to a missing snapshot succeed, then reads return `[]`; resolved calls are over-marked (must fix 1) |
| Contract fit | PASS | `StoreSymbolIndex` has all five protocol methods; `export_json` matches section 8 field for field |

**Timings** at 50,000 nodes and 150,000 edges (file database): `write_nodes` 3.9 s, `write_edges` 3.0 s, `search_text` 18-53 ms, `graph()` 3.6-5.0 s, `reverse_reach` at depth 3 0.2 ms (unlimited depth: about 2 s), `export_json` 2.9 s. Fast enough for medium repositories.

**Must fix** (issue #12, part 1)
1. `sqlite.py:138-157`: `mark_resolved_calls` matches on caller and line only, so in `foo(mystery())` both calls are marked resolved when only `foo` resolved. The evaluation's count of unresolved calls would be too low.

**Should fix** (issue #12, parts 2 and 3)
1. Writes for a snapshot with no row succeed silently; make them raise.
2. Indexing the same commit twice raises `IntegrityError` and there is no `delete_snapshot`.
3. On a failed schema check the connection stays open, which locks the file on Windows.
4. The trickiest line of the traversal (`graph.py:63`) has no test.
5. `graph()` takes twice as long as it needs to (3.6 s against 1.7 s).

**Your decisions** (the PR's nine, then three from the review; write your answer next to each)

| # | Question | Recommendation |
| --- | --- | --- |
| 1 | `source` and `limits_hit_json` added to snapshots | Accept: the contract wins over the brief's table |
| 2 | How `mark_resolved_calls` works | Accept after must fix 1 |
| 3 | Duplicate node ids raise | Accept; the pipeline (T18) catches this per file and records it |
| 4 | `nodes_by_key` returns a list across snapshots | Accept |
| 5 | Snapshot found by id prefix | Accept, with should fix 1 |
| 6 | Negated BM25, weights 10/5/2/1/1, quoted OR query | Accept; "exact name first" really means "almost always" |
| 7 | Traversals exclude start nodes; `depth=None` means no limit | Accept; consider a `min_score` floor for the impact engine |
| 8 | Extra methods | Accept |
| 9 | WAL mode | Accept; you will see `-wal` and `-shm` files next to the database |
| 10 | `copy_unchanged` copies nodes only; raw calls are not copied | Accept; re-parsing everything is cheap, so T18 does full re-index in v1 |
| 11 | Where do parse errors (`ParseResult.errors`) live? | In the module node's `attrs["errors"]`, written by the pipeline (D-13) |
| 12 | Snapshots are never pruned | `delete_snapshot` now (should fix 2); a retention policy later |

**Try it yourself** (PowerShell, after `gh pr checkout 5`)

```powershell
python -m pytest -q tests/store    # expect: 24 passed
python -c "from codeatlas.store.graph import reverse_reach; import networkx as nx; g=nx.MultiDiGraph(); [g.add_edge(a,b,kind='calls',confidence=c) for a,b,c in [('a','b',0.9),('b','d',0.9),('a','c',1.0),('c','d',0.5)]]; print(reverse_reach(g,['d']))"
```

The second prints `{'b': 0.9, 'c': 0.5, 'a': 0.81}`: `a` reaches `d` by two paths, 0.9 × 0.9 = 0.81 and 1.0 × 0.5 = 0.5, and keeps the better one. Compare this with your answer to Q3 in `docs/decisions.md`.

**Read these yourself**
- `src/codeatlas/store/graph.py:40-74` (`_walk`): the impact engine's confidence numbers come from this round-by-round search; line 63 is the untested one.
- `src/codeatlas/store/sqlite.py:138-157` (`mark_resolved_calls`): decides what the evaluation counts as resolved.
- `src/codeatlas/store/schema.py:40, 87-110`: why each node has an integer `pk` as well as its text `id`, and how triggers keep FTS in step.
