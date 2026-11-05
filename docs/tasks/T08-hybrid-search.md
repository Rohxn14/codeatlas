# T08: Hybrid search

> **Reading note.** This brief is history. It is what a cloud session was told to build, kept so you can see what was asked; it is not an instruction for new work.
> - **Built in**: pull request #21, with fixes in #27.
> - **Read first**: `docs/explainers/search.md`, for what was actually built and why.
> - **Code**: `src/codeatlas/search/`. **Tests**: `tests/search/`.
> - **Then** read this brief and its review at the end: the gap between them is where the interesting questions are.
> - Reading order, glossary and how to study a module: `docs/README.md`.

**Wave**: 2 (all of Wave 2 runs in parallel)
**Branch**: keep the one the cloud environment gives you

## Goal

Questions use words, not identifiers: "where are users saved?" should find `UserRepo.save` even though the word "saved" appears nowhere in its name. This task builds the search the agent (T09) starts from: BM25 over the full-text index, vector search over symbol embeddings, reciprocal rank fusion of the two, then one hop along the graph from the top hits, returned as a ranked context pack of `file:line` spans.

## Files you may create or edit

- `src/codeatlas/search/` (new package), including `__main__.py` for a command-line entry
- `src/codeatlas/store/sqlite.py`: add exactly two methods, `write_embeddings(rows)` and `embeddings(snapshot_id, model) -> tuple[list[str], numpy.ndarray]`, using the existing `embeddings` table; no schema change
- `tests/search/`, `tests/data/search/`
- `docs/explainers/search.md`

Do not edit `cli.py`: T18 edits it in parallel. The `python -m codeatlas.search` entry below is enough; the `codeatlas search` command is wired up later.

## Part 1: embeddings (`search/embed.py`)

`build_embeddings(store, snapshot_id, embedder, repo_root: Path | None = None) -> int` embeds every FUNCTION, CLASS, INTERFACE, TEST and MODULE node of the snapshot that has no embedding yet for the embedder's model. The text for a node: kind, qualname, path, signature, docstring, and, when `repo_root` is given, the first 15 lines of its body read from disk (decoded with replacement). Use T04's `EmbeddingClient` (bge-small by default, cached by text hash); batch the calls; store float32 vectors. Re-running is cheap: only missing nodes are embedded.

## Part 2: search (`search/hybrid.py`)

`HybridSearch(store, snapshot_id, embedder)` with `search(query, k=10, expand=True, min_confidence=0.5) -> list[SearchHit]`:

1. **BM25**: `store.search_text(snapshot_id, query, 50)`.
2. **Vectors**: embed the query, cosine similarity against the snapshot's matrix (NumPy, brute force; fine up to about 100,000 nodes), top 50. If the snapshot has no embeddings, say so in the result and continue with BM25 only.
3. **Fusion**: reciprocal rank fusion, score = Σ 1 ÷ (60 + rank) over the lists a node appears in.
4. **Graph expansion**: from the top `k` fused hits, one hop along CALLS (both directions), CONTAINS and INHERITS edges with confidence at least `min_confidence`; a neighbour scores its hit's score times the edge confidence times 0.5, and is added only if not already present.
5. **Result**: `SearchHit` has the node, its score, which sources found it (`bm25`, `vector`, `graph`), and for graph hits the edge that brought it in.

`context_pack(hits, max_lines=200) -> list[Span]`: `path:start-end` spans in score order, merged when they overlap, cut at `max_lines` in total, each with a one-line reason. T09's agent puts these in front of the model.

`python -m codeatlas.search "query" [--db PATH] [--snapshot ID] [--k 10] [--no-expand] [--embed]` prints the hits; `--embed` builds missing embeddings first.

## Part 3: measure it

`tests/data/search/fixture_queries.json`: 15 questions about the fixture app written in plain words (for example "where is a new user validated?", "which component shows one user?", "what handles the users list route?"), each with the node keys a good answer must include. Write the questions without copying identifiers from the code. A script in `tests/data/search/` or `scripts/` indexes the fixture with `build_graph` (the pipeline core, `src/codeatlas/indexer/pipeline/`), builds embeddings, and reports recall@5 and MRR for four configurations: BM25 only, vectors only, fused, fused plus graph expansion. Report the table in the pull request and the explainer, and say which questions every configuration misses.

## Tests

Offline: a fake embedder with deterministic vectors (for example a hash of words into a small vector) so fusion, expansion and ranking have exact expected outputs; RRF on two hand-made lists; expansion respects `min_confidence` and adds no duplicates; `context_pack` merges overlapping spans and stops at `max_lines`; a snapshot without embeddings falls back to BM25 and says so; the two new store methods round-trip. No test downloads a model.

## Done when

Tests pass on Linux and Windows CI; the four-configuration table on the fixture is in the pull request, using the real bge-small model in the cloud session (the setup script pre-downloads it; if it is missing, say so and report BM25 only); the explainer covers the five steps with a worked example query on the fixture and why fusion uses ranks rather than raw scores.

## Review of PR #21 (Nov 3)

**Verdict**: merge after small fixes; done in the "Wave 2 review fixes" pull request.

**The PR's table** (bge-small, before the resolvers): recall@5 BM25 0.267, vectors 0.733, fused 0.600, fused plus graph 0.600. Vectors alone beat fusion on this fixture, and the PR says so. The reviewer could not download bge-small here (HTTP 403 from Hugging Face through this proxy), so the vector rows could not be re-run; the BM25 row reproduced exactly.

**Main finding (fixed)**: graph neighbours were appended after the top k and never re-sorted, so "fused plus graph" recall@5 always equalled "fused": the graph hop could not change what the agent sees first. Now neighbours compete for the k places.

**Also fixed**: expansion skips EXTERNAL and path-less nodes (no `:1-1 vitest.expect` spans in the context pack); a model that cannot be loaded falls back to BM25 with a note instead of crashing; row norms are computed once and the candidate pool uses `argpartition` (the reviewer measured 106 ms per query at 50,000 vectors, mostly sorting).

**Still open**: re-run `scripts/eval_search.py` with bge-small in a cloud session, now that the graph hop counts and the resolvers exist; three questions leak identifier words (`remembers`, `next`, `name`); `context_pack` merges only the first overlapping span.

**Your decisions**: let graph hits compete for the top k (done, recommended); keep equal-weight fusion until the 40-repository suite gives more questions (recommended); expand CONTAINS only from a class to its methods, not to whole files (recommended, not done).

**Read these yourself**: `search/hybrid.py` (`search` and `_expand`); `search/hybrid.py` (`context_pack`); `tests/data/search/fixture_queries.json` (check the questions say what you mean).
