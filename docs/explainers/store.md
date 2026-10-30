# The graph store

Modules: `src/codeatlas/store/schema.py`, `src/codeatlas/store/sqlite.py`,
`src/codeatlas/store/symbols.py`, `src/codeatlas/store/graph.py`.

## What

`GraphStore` keeps every indexed snapshot of every repository in **one SQLite file**:
the files discovery saw, the nodes adapters produced, the edges resolvers and linkers
found, the raw calls that may or may not have become edges, a full-text index over
symbol names and docs, and (from T08) embeddings. On top of the tables it offers:

- bulk writes (`write_files`, `write_nodes`, `write_edges`, `write_raw_calls`);
- lookups (`node`, `nodes_by_key`, `nodes_by_name`, `nodes_in_file`, `edges_from`,
  `edges_to`);
- `search_text`, BM25 ranking over the full-text index;
- `symbol_index(snapshot_id)`, the contract's `SymbolIndex` for resolvers and linkers;
- `graph(snapshot_id)`, a NetworkX `MultiDiGraph` view, plus traversal helpers in
  `store/graph.py` (`callers`, `callees`, `reverse_reach`);
- `copy_unchanged` and `file_hashes` for incremental re-indexing;
- `export_json`, the scorer's format from contract section 8.

### Schema (version 1)

| Table | Columns | Keys and indexes | Notes |
| --- | --- | --- | --- |
| `meta` | key, value | PK key | `schema_version = "1"` |
| `snapshots` | id, repo, commit_sha, indexed_at, indexer_version, source, limits_hit_json | PK id; (repo, indexed_at) | `limits_hit` stored as a JSON list |
| `files` | snapshot_id, path, language, tier, sha256, size_bytes | PK (snapshot_id, path) | |
| `nodes` | pk, id, key, snapshot_id, kind, language, name, qualname, path, start_line, end_line, start_col, end_col, signature, docstring, owner_key, attrs_json | PK pk; UNIQUE id; (snapshot_id, key), (snapshot_id, name), (snapshot_id, path), (snapshot_id, owner_key) | `pk` is the integer row the FTS index points at |
| `edges` | snapshot_id, src_id, dst_id, kind, confidence, resolution, line, attrs_json | (snapshot_id, src_id, kind), (snapshot_id, dst_id, kind) | No uniqueness: two calls on different lines are two edges |
| `raw_calls` | snapshot_id, caller_key, callee_text, name, receiver, line, resolved | (snapshot_id, caller_key) | `resolved` is 0 or 1 |
| `nodes_fts` | name, qualname, signature, docstring, path | FTS5, external content = `nodes` | Kept in step by three triggers |
| `embeddings` | node_id, model, dim, vector | PK (node_id, model) | float32 blob; written by T08 |

Enums are stored as their string values (`"calls"`, `"self_method"`), and `attrs` as
JSON text, so the file is readable with any SQLite browser.

## Why

- **SQLite, not a graph database.** The graph is small enough for one machine (tens of
  thousands of nodes per snapshot), and most questions are indexed lookups: "nodes
  named `save`", "edges into this id". SQLite ships with Python, needs no server, is
  one file you can copy or delete, works identically on Windows and Linux, and its FTS5
  module gives BM25 text search for free. Multi-hop questions (callers of callers, impact)
  are handed to NetworkX, which loads one snapshot in about a second for 50,000 nodes.
  Rejected: Neo4j or Kùzu (a server or a native dependency to install, a second query
  language to learn, and no full-text search as simple as FTS5), and a pickled NetworkX
  graph alone (no indexed lookups, no text search, the whole graph in memory for every
  query).
- **Nodes have both an integer `pk` and the text `id`.** FTS5 external-content tables
  link to their content by an integer rowid. Declaring `pk INTEGER PRIMARY KEY` makes
  that rowid permanent; an undeclared rowid can be renumbered by `VACUUM`, which would
  silently point the search index at the wrong nodes.
- **External content plus triggers.** The text lives once, in `nodes`; `nodes_fts`
  holds only the index. SQLite does not update an external-content index by itself, so
  insert, update and delete triggers do it. Rejected: a standalone FTS table (every
  name and docstring stored twice).
- **Query words are quoted and OR-ed.** A user typing `save(` or `a AND (*` would
  otherwise send FTS5 syntax errors. Each `\w+` word becomes a quoted phrase; `OR`
  lets a partial match still rank. BM25 weights favour the name (10) over the qualname
  (5), signature (2), docstring and path (1). A node whose name equals the query is
  then moved to the top, so an exact name match always comes first.
- **Duplicate node ids are an error.** Silently keeping one would hide a symbol (the
  "no silent gaps" rule), so `write_nodes` names the repeated ids and writes nothing.
- **`edges_from`/`edges_to` find the snapshot from the snapshots table.** The edge
  indexes start with `snapshot_id`, and a node id is `{snapshot_id}/{key}`. Splitting on
  the first `/` would break for a repo name such as `org/app`, and edge endpoints need
  not be nodes, so the store picks the snapshot id that prefixes the node id.
- **One transaction and one `executemany` per bulk write.** Committing row by row is
  hundreds of times slower; writing 50,000 nodes and 50,000 edges takes under two
  seconds this way.
- **Schema version in `meta`.** An old file raises `StoreError` telling the user to
  delete it and re-index, instead of failing later with a confusing SQL error.
- **FTS5 is checked at start-up.** `ensure_fts5` creates a throwaway FTS5 table in
  memory; if that fails the error names the SQLite version.

## How

**Writing a snapshot.** The pipeline calls `create_snapshot`, then `write_files`,
`write_nodes` (each insert fires the trigger that adds the row to `nodes_fts`),
`write_edges` and `write_raw_calls`. `mark_resolved_calls` then sets `resolved = 1` on
every raw call for which a CALLS edge exists from the same caller on the same line, so
the eval can count what stayed unresolved.

**Incremental re-index.** `file_hashes(old)` gives `{path: sha256}`. Files whose hash
is unchanged are passed to `copy_unchanged(old, new, paths)`, which runs one
`INSERT ... SELECT` that rewrites `id` to `{new}/{key}` and `snapshot_id` to `new`,
keeping the key. Edges are not copied: a call from an unchanged file may point into a
changed one, so the pipeline recomputes them.

**Search.** `search_text(sid, "save user", 5)` sends the FTS5 query
`"save" OR "user"`, joins `nodes_fts` to `nodes` on `pk`, keeps rows of snapshot
`sid`, orders by `bm25(...)` (lower is better in SQLite; the store returns its negation,
so higher is better), then moves exact name matches first and keeps the top 5.

**Best-path traversal.** `reverse_reach(g, targets, kinds, depth)` walks edges
backwards, round by round (like Bellman-Ford). Each node keeps the best product of
confidences found so far; a round extends only the nodes that improved in the previous
round, using their scores from the start of the round, so round *i* has tried every
path of up to *i* edges. Confidences are at most 1, so a cycle never improves a score
and the walk ends even without a depth limit.

Worked example: `a → b` (0.9), `b → d` (0.9), `a → c` (1.0), `c → d` (0.5), all CALLS.
`reverse_reach(g, ["d"])`:

| Round | Frontier | Updates |
| --- | --- | --- |
| 1 | d | b = 1 × 0.9 = 0.9; c = 1 × 0.5 = 0.5 |
| 2 | b, c | from b: a = 0.9 × 0.9 = 0.81; from c: a would be 0.5 × 1.0 = 0.5, not better |
| 3 | a | nothing reaches a; stop |

Result: `{b: 0.9, c: 0.5, a: 0.81}`; the start node `d` is left out. `callers` and
`callees` use the same walk over CALLS edges only, with a per-edge `min_confidence`.

## Where

- **Contract types**: `Snapshot`, `FileRecord`, `Node`, `Span`, `Edge`, `RawCall`, the
  enums `NodeKind`, `EdgeKind`, `Resolution`, `Tier`, and the id helpers
  `make_node_id`; `StoreSymbolIndex` satisfies the `SymbolIndex` protocol from
  `indexer/adapter.py` (checked with `isinstance` in the tests).
- **Upstream**: the indexing pipeline (later wave) writes what discovery (T00), the
  adapters (T01, T02, structural tier) and the repository layer (T15) produce, and
  hands `symbol_index(...)` to resolvers and linkers.
- **Downstream**: hybrid search reads `search_text` and the `embeddings` table (T08);
  the impact engine uses `graph(...)` with `reverse_reach`; the agent and MCP server
  use the lookups; the graph-accuracy scorer (T05) reads `export_json`.
