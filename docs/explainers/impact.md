# Impact engine and test selection

## What
Given a change (a unified diff, a list of files with line ranges, or symbol keys), the engine ranks what the change could break and which tests to run. Every result carries its evidence: the path through the graph, the import, or the history behind it. `impact(store, snapshot_id, changes)` returns an `ImpactResult` with ranked `targets`, ranked `tests`, and `warnings` for what could not be mapped (a file outside the snapshot, a file with no symbols). `evaluate.py` scores it against mutation truth and held-out commits.

## Why
- **Four separate signals, then a combination.** A single blended score cannot say *why* a test was chosen. Each signal keeps its own evidence and the combination rule is one small function, so the owner can rewrite it (v2) and the evaluation can switch rules.
- **Highest signal (`max`) by default, `noisy_or` as a switch.** Q3 asks whether more paths should raise the score. Adding paths inside the graph signal double-counts one cause (three callers of one hub are one change). `noisy_or` lets different signals agree (`1 - prod(1 - s)`). I scored both: at the cut-off with the best F1 (0.3) they select the same tests on polyglot_app and itsdangerous; at 0.5 `noisy_or` is better on itsdangerous (F1 0.76 against 0.71) but still below `max` at 0.3 (0.84), so `max` stays. The failure case for adding: a utility file that is imported, co-changed and tested by convention scores high on three weak, correlated signals.
- **Decay folded into edge confidence.** `store/graph.py` multiplies confidences along a path, so multiplying each CALLS/IMPORTS confidence by 0.8 on a copy of the graph gives `product(confidence) * 0.8^hops` without touching the store. Rejected: writing a second search (two implementations to keep in step).
- **Depth 4, decay 0.8.** A four-hop chain of perfect edges still scores 0.41, above a name guess; past that, call graphs fan out and the scores are noise.
- **TESTS edges at 0.9 of their confidence.** After D-23 what remains is intended coverage (convention, direct, import-scoped). Co-change gets 0.7 because history is correlation.
- **Test files are the unit of selection.** Mutation truth lists failing test files, and a runner takes files. Picks for test functions stay in the result; `test_files()` keeps the best pick per file.

## How
1. **Changes to symbols** (`symbols.py`). For each range, the innermost FUNCTION/CLASS/INTERFACE/TEST holding each changed line (exact: it can only change at a symbol's first line or the line after its last, so those points are enough). A range touching no symbol maps to the module. A file with no symbols maps to its module (warning); no ranges means the module and every symbol.
2. **Graph** (`engine.py`). `reverse_reach` over CALLS and IMPORTS on the decayed graph, depth 4. Owner classes of changed methods are extra starts at 0.8, since imports point at the class. The best path is rebuilt by walking back to the neighbour whose score times the edge confidence equals this node's score.
3. **Imports.** Importers of anything in a changed file that the graph signal did not already reach: `confidence * 0.8 * 0.5` (the file changed, the imported thing may not have).
4. **Co-change.** CO_CHANGES edges out of the changed modules: `confidence * 0.7`, with support and commit count as evidence.
5. **Tests.** TESTS edges into a changed node, its module, or any reached node: `reach * confidence * 0.9`. A changed test is always selected at 1.0.
6. **Combine** per target and drop below 0.05. A test target is a TEST node or a test file; `__init__.py` and `conftest.py` are not tests.

Worked example, the test fixture in `tests/impact/impact_graph.py`, a change to `Repo.save` (line 3):
`create` calls `Repo.save` at 0.9 → 0.9 × 0.8 = 0.72. `handler` calls `create` at 1.0 → 0.72 × 0.8 = 0.576. `test_create` calls `create` at 1.0 → also 0.576, so `tests/test_service.py` is selected with the path `Repo.save <-calls(0.9)- create <-calls(1)- test_create`. `test_save` has a TESTS edge to `Repo.save`: 1.0 × 1.0 × 0.9 = 0.9, the top pick.

**Evaluation.** Mutation truth: the mutated function's span is the change; the truth is its failing test files (vitest reports bare file names, matched by path suffix). Precision, recall, F1 (macro over mutants) at the natural cut-off (score ≥ 0.3), at k = 5, 10, plus the share of test files skipped. Mutants no test catches cannot score recall (Q4): they are listed apart. Baselines: run everything, tests importing the changed file, co-change alone. Co-change: `ImpactPredictor` indexes HEAD once and reads history up to each held-out commit.

**Why precision is the hard part.** Recall is cheap: run everything and it is 1.0. The value of selection is the tests *not* run, and every wrong inclusion costs that. Real call graphs funnel into a few hubs (a `serialize` helper that all tests reach), so a change to a hub makes most tests "affected" and precision collapses toward run-all. Unresolved calls (dynamic dispatch, fixtures) hurt recall in the other direction. The cut-off of 0.3 was chosen on the same two small benchmarks it is reported on, so its F1 is optimistic.

## Where
Reads `GraphStore` (`graph()`, `nodes_in_file`, `module_for_path`, `edges_from`) and `store/graph.reverse_reach`; uses `repo/test_conventions.classify`. Contract types: `Node`, `NodeKind`, `Edge`, `EdgeKind` (CALLS, IMPORTS, TESTS, CO_CHANGES), `Resolution`. Used by `agent/tools.py` (`impact`, `select_tests`, same names and result shapes, plus an `evidence` list on each row), by `eval/cochange/predictors.py` (`ImpactPredictor`) and by `scripts/evaluate_impact.py`. The HTTP linker's CALLS_HTTP and HANDLES edges are not walked yet; add them to `WALK_KINDS` once T11's edges exist.
