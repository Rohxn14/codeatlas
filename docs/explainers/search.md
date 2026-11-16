# Hybrid search (T08)

## What

Takes a question in plain words ("what hands out the next free number for a new person?") and returns the symbols most likely to answer it, ranked, plus a *context pack*: `path:start-end` line ranges the agent (T09) can put in front of the model. Code: `src/codeatlas/search/` (`embed.py`, `hybrid.py`, `__main__.py`) and two new store methods, `write_embeddings` and `embeddings`.

## Why

- **Two searchers, because each fails differently.** BM25 needs the question's words to appear in names, signatures, docstrings or paths; vectors match meaning but blur exact names. Running both and fusing covers both.
- **Fusion by rank, not score.** BM25 scores (unbounded, depend on corpus statistics) and cosine similarities (about 0.3 to 0.9) are on unrelated scales; adding or averaging them needs tuning that breaks per repository. Reciprocal rank fusion only uses positions, so it needs no tuning. Rejected: weighted score sum, learned re-ranker (cost, and nothing to train on yet).
- **Brute-force NumPy cosine.** One matrix product over at most ~100,000 rows takes milliseconds; a vector index (FAISS, sqlite-vss) would add a dependency for no gain at this size.
- **One graph hop, discounted.** The code that answers a question is often the neighbour of the one that matches (the class around a method, the callee). One hop at half weight adds that context without flooding results. Rejected: multi-hop walks (noise grows fast).
- **Embeddings stored per node id and model**, in the existing table, so changing model never mixes vectors.

## How

0. **Code or documentation, never both (D-42).** `search(query)` searches code; `search(query, docs=True)` searches only the `SECTION` nodes of documentation files (their text is the node's docstring). Both lists below are filtered the same way, and a documentation search skips step 4, because a section's only neighbour is its own file.
1. **BM25**: `store.search_text(snapshot, query, 50)`, an FTS5 query over name, qualname, signature, docstring, path.
2. **Vectors**: embed the query, divide by norms, one matrix product against the snapshot matrix, take the top 50 (ties broken by node id so output is deterministic). With no embeddings, a note says so and BM25 alone is used.
3. **Fusion**: `score = sum of 1/(60+rank)` over each list containing the node (rank starts at 1).
4. **Expansion**: for each of the top `k` hits, follow CALLS (both directions), CONTAINS and INHERITS edges with confidence ≥ `min_confidence`. A new neighbour scores `hit.score × edge.confidence × 0.5`; nodes already present are skipped; if two hits reach the same neighbour the better score wins.
5. **Result**: `SearchHit(node, score, sources, via)`; `context_pack` walks hits in score order, merges overlapping ranges in the same file, and stops at `max_lines`.

Worked example on the fixture, query "what hands out the next free number for a new person?" (real bge-small, node text includes 15 body lines):

| node | score | found by |
| --- | --- | --- |
| `UserService._next_id` | 0.0328 | bm25 + vector (rank 1 in one list, 2 in the other: 1/61+1/62) |
| `UserApi.getUser` | 0.0308 | bm25 + vector |
| `fetchUser` | 0.0296 | bm25 + vector |
| `UserService` (class) | 0.0164 | graph: CONTAINS edge from `_next_id`, 0.0328 × 1.0 × 0.5 |

## Where

Reads `GraphStore` (`search_text`, `node`, `nodes`, `edges_from/edges_to`, the new embedding methods) and T04's `EmbeddingClient`. Uses contract types `Node`, `NodeKind`, `Edge`, `EdgeKind`. `ContextSpan` is a search-local type because the contract's `Span` has no path. T09's agent calls `HybridSearch.search` then `context_pack`. Run: `python -m codeatlas.search "query" --db codeatlas.db --embed`.

## Measured (15 fixture questions, bge-small, `python scripts/eval_search.py`)

| configuration | recall@5 | MRR |
| --- | --- | --- |
| BM25 only | 0.267 | 0.164 |
| vectors only | 0.733 | 0.579 |
| fused | 0.600 | 0.356 |
| fused + graph | 0.500 | 0.363 |

Re-measured on Nov 16, 2026, after documentation sections were added (D-41, D-42). Just before that change the same script gave BM25 0.267 / 0.144, vectors 0.733 / 0.579, fused 0.600 / 0.390, fused + graph 0.500 / 0.397, so the "fused + graph" row of the first write-up (0.600 / 0.398) had already drifted. With sections mixed into one list the numbers were BM25 0.200 / 0.110 and fused 0.400 / 0.261, which is why the two searches are kept apart. The small MRR moves that remain come from BM25: its word statistics are counted over one index that now also holds the sections. The documentation search itself is not measured yet: there are no questions with a section as the right answer.

Every configuration misses (top 5): "where is a new account checked for a missing name?", "which component shows one person in the page list?", "where does the browser ask the server for all people?", "what is the generic storage base that keeps things by number?".

Honest reading: on this tiny fixture (81 embedded nodes) fusion is *worse* than vectors alone, because the BM25 list is mostly noise for questions that deliberately avoid identifiers, and RRF gives it equal weight. Graph expansion adds a hair of MRR but no recall@5, since it appends below the top hits. Fifteen questions is a small sample, so differences of one question (0.067) are not strong evidence. A weighted fusion (e.g. BM25 at 0.5) is the obvious next experiment; I did not do it because the brief fixes the formula.
