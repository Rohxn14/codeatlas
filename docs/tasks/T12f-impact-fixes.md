# T12f: Impact engine review fixes

**Wave**: 3 fixes (runs in parallel with T11f and T17f; no file overlap)
**Branch**: keep the one the cloud environment gives you
**Why**: T12's review (end of `docs/tasks/T12-impact-engine.md`). The engine ignores T11's route edges, though T11 merged first; `parse_diff` silently drops some changes; and the co-change numbers are flattered by structure from the held-out commits.

## Files you may edit

- `src/codeatlas/impact/`, `src/codeatlas/agent/tools.py` (only the `impact`/`select_tests` bodies and the dead helper below), `eval/cochange/predictors.py` (only your predictor), `scripts/evaluate_impact.py`
- `tests/impact/`, `tests/data/impact/`, `docs/plans/T12.md`, `docs/explainers/impact.md`

## Must fix

1. **Follow HANDLES and CALLS_HTTP** (`impact/engine.py:31-32`). Add both kinds to `WALK_KINDS` and `LOAD_KINDS`, so a change to a handler walks handler ← route ← client. Example: on `eval/fixtures/polyglot_app`, impact on `backend/routes.py::list_users` today reaches only `backend/tests/test_routes.py::` and `backend/app.py::`; `frontend/src/api/client.ts::fetchUsers` must appear. Add a test with a ROUTE node. Regenerate the mutation tables, and add the route-handler worked example the brief asked for. (T11f is adding the missing fixture client calls in parallel; use whatever main has when you run, and say which.)
2. **`parse_diff` drops renames, binary and mode-only changes** (`impact/diff.py:25-46`). `parse_diff("diff --git a/x.py b/y.py\nsimilarity index 100%\nrename from x.py\nrename to y.py\n")` returns `[]`. Take the path from the `diff --git a/X b/Y` line (`rename to` when present), and emit a whole-file `Change` for any section with no hunks. A rename should also report the old path (every importer of it breaks). Test all three.
3. **Hunk lines starting with `--- ` or `+++ ` are read as file headers** (`diff.py:34-37`). Removing an SQL line `-- old` and adding `++ new` creates `Change(path='new', ...)`. Accept `---`/`+++` only before the first `@@` of a section. Diffs without `diff --git` headers: handle them per `---`/`+++` pair, or reject with a warning. Test it.

## Should fix

4. **Co-change leakage** (`eval/cochange/predictors.py:106-115`, `scripts/evaluate_impact.py:439`). The index is built at HEAD, so imports added by the held-out commits are already in the graph. Build the one index at the parent of the oldest held-out commit. Report the new numbers; if the engine no longer beats history, say so.
5. **The natural cut-off was tuned on its own test data** (`impact/models.py:34`, `test_threshold=0.3`). Also report leave-one-benchmark-out: tune on one benchmark, score on the other.
6. **The PR's mutation table lacked P@10 and R@10**: paste the full `table()` output in the new pull request.
7. **A range touching a symbol drops module-level lines in it** (`impact/symbols.py:75`). `Change("app/service.py", ((1, 5),))` maps only to `create`; also add the module node when any line in the range lies outside every symbol.
8. **`_trace` never ends with decay 1.0** on a cycle (`engine.py:149`). Keep a visited set, and require `0 < decay < 1` in `ImpactConfig.__post_init__`.

## Later

9. Delete `agent/tools.py` `_impact_scores` (no callers left).
10. In the agent `impact` tool, sort `co_changed_files` by its own history confidence; take an `affected` row's confidence from non-history evidence.
11. Decode git's octal-escaped quoted paths (`"a/d\303\251.py"`) in `_strip`.
12. `ImpactPredictor`: count files deleted after the held-out commit separately instead of returning `[]` silently.

## Done when

The fixes above, with tests; the new mutation and co-change tables and the route worked example in the pull request; `pytest -q` and `ruff check .` pass; explainer updated (signals now include HTTP edges; the leakage fix). Pull request title: `T12f: impact engine review fixes`.
