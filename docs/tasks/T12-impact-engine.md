# T12: Impact engine and test selection

**Wave**: 3 (all of Wave 3 runs in parallel)
**Branch**: keep the one the cloud environment gives you

## Goal

Given a change (a diff, or a list of changed files and symbols), rank what it could break and which tests to run, with the evidence for each: the path through the graph, the import, or the history. Score it against the truth T10 built: mutation truth (which tests really fail) and held-out commits (which files really changed together). This is the module the owner will rewrite as v2, so the plan, the scoring and the explainer matter as much as the code.

## Plan first, then build

Write `docs/plans/T12.md` (about one page) as your first commit, then keep going without waiting: the four signals and how each is scored, how they combine (and your answer to Q3 in `docs/decisions.md` if the owner has not answered it), how a diff becomes changed symbols, the evaluation runs, and what you expect to get wrong.

## Files you may create or edit

- `src/codeatlas/impact/` (new package)
- `src/codeatlas/agent/tools.py`: replace only the bodies of the v0 `impact` and `select_tests` tools with calls into your engine, keeping their names, schemas and result shapes
- `eval/cochange/predictors.py`: add one predictor class that uses your engine (keep the existing two)
- `tests/impact/` (test file names unique across `tests/`), `tests/data/impact/`
- `docs/plans/T12.md`, `docs/explainers/impact.md`

Do not edit `cli.py` (wired up later), the resolvers, the store or the pipeline.

## The engine

`impact(store, snapshot_id, changes) -> ImpactResult`, where `changes` is a list of changed files with optional line ranges (from a unified diff via `parse_diff(text)`, or given directly).

1. **Map changes to symbols**: each changed line range to the innermost FUNCTION, CLASS or TEST node whose span holds it; a changed file whose language has no symbols maps to its module node.
2. **Graph reach**: walk CALLS (reversed) and IMPORTS (reversed) from the changed symbols up to depth `d` (default 4) with `store/graph.py`'s best-path search. A path's score is the product of its edge confidences times a decay per hop (default 0.8).
3. **File imports**: modules that import a changed module or a symbol in it (imports point at symbols; see the T09 fix in `agent/tools.py`'s `get_imports`).
4. **Co-change**: the changed files' CO_CHANGES neighbours, weighted by their history confidence.
5. **Test conventions**: TESTS edges by naming convention from changed modules.
6. **Combine** per target: v1 takes the highest signal, as the project plan says; if Q3 is answered, follow the owner's formula. Keep each target's evidence: the best path (as node keys with edge kinds and confidences), or the import, or the co-change support.
7. **Select tests**: rank TEST nodes and test modules by the score of what they reach (through TESTS edges and through CALLS from test functions), with the evidence for each.

`ImpactResult` holds ranked targets and ranked tests, each with score and evidence, plus what could not be mapped (a changed file not in the snapshot, a change in a file with no symbols) as warnings.

## Evaluation (`src/codeatlas/impact/evaluate.py`, plus a `scripts/` entry point)

- **Mutation truth** (`eval/mutants/truth/*.json`, caller basis `calls-edges`): for each mutant, the change is the mutated function's span; the truth is its failing test files. Report precision, recall and F1 of the selected tests at their natural cut-off and at k = 5 and 10, and the share of tests skipped (the point of test selection), per benchmark. Mutants no test catches are reported separately: they cannot score recall (Q4 in `docs/decisions.md`).
- **Co-change benchmark** (`python -m eval.cochange` with your predictor added): precision and recall at 5 and 10 against the two existing predictors. Build one index of the repository and read history up to each held-out commit; do not re-index per commit.
- **Baselines** on the same mutation truth: run every test; tests whose module imports the changed module; the co-change predictor alone.

## Decide in your plan

1. Depth and decay defaults, and why.
2. Whether several weak signals should add up (Q3); if you change the v1 rule, keep "highest signal" as a switch so both can be scored.
3. How weak TESTS edges should count. D-23 is applied: the deep resolvers no longer make TESTS edges from name guesses, but the repository layer's naming-convention TESTS edges (`convention`, from `repo/test_conventions.py`) remain.

## Tests

On small repositories built in the test: each signal alone, with exact scores; combination; a diff touching two functions and a README; a change in a file outside the snapshot (a warning); test selection through a TESTS edge and through a test's CALLS; the evaluation's metrics on hand-made truth. No network.

## Measure and report

In the pull request: the mutation-truth table for both benchmarks against the three baselines; the co-change table with your predictor; three worked examples from the fixture (a change to `Repo.save`, to `UserCard`, to a route handler once T11's edges exist on main), each with the ranked tests and their evidence.

## Done when

Tests pass on Linux and Windows CI; the plan is committed; the tables are in the pull request; the agent's `impact` and `select_tests` use the engine; the explainer covers each signal, the combination rule, the evaluation and why precision is the hard part.

## Review (Nov 3)

**Verdict**: merged (#30); mostly meets "Done when". Signals, evidence, warnings and agent wiring are there; one metric checked by hand (polyglot run-all F1 0.521) matches. Must fix: it ignores T11's HANDLES/CALLS_HTTP edges; `parse_diff` silently drops renames and binary changes, and misreads hunk lines starting `---`/`+++`. Should fix: the co-change comparison leaks structure from held-out commits, and the test cut-off was tuned on the data it is scored on. Fixes: `docs/tasks/T12f-impact-fixes.md`.

**Read these yourself**: `impact/engine.py` (the walk and the combination rule), `impact/evaluate.py` (how precision and recall are counted), `docs/plans/T12.md` (its answer to Q3).
