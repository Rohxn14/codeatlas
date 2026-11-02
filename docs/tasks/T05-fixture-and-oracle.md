# T05: Polyglot fixture, SCIP oracle and graph scorer

**Wave**: 1 (parallel with T01 to T04)
**Branch**: `task/T05-fixture-oracle`

## Goal

Build the measuring stick for the indexer before the resolvers exist: a small mixed Python/TypeScript app with hand-labelled ground truth, a runner that produces precise reference ground truth from SCIP indexers on any repo, and a scorer that compares a CodeAtlas graph export with either.

## Files you may create or edit

- `eval/fixtures/polyglot_app/` (the app, its tests, `expected_graph.json`, `LABELS.md`)
- `eval/oracle/` (SCIP runners, converters, scorer, CLI entry)
- `tests/eval/`
- `docs/explainers/graph-eval.md`

## Part 1: the fixture app

A tiny but realistic app, about 25 to 40 functions in total:

- `backend/` (Python, FastAPI): a `UserService` class with methods, a base repository class and a subclass that overrides a method, an aliased import (`from .repo import Repo as BaseRepo`), a decorator that wraps functions, a registry dict that calls handlers by name (`HANDLERS[name](...)`, a deliberate dynamic call), a `getattr` call, routes `GET /api/users`, `GET /api/users/{id}`, `POST /api/users` with an `APIRouter(prefix="/api")`, and pytest tests.
- `frontend/` (TypeScript): an API client using `fetch` with a literal URL and a template-literal URL, an `axios.create({baseURL: "/api"})` instance, a class implementing an interface, a re-export barrel file (`index.ts`), one React component rendering another, and Vitest tests with nested `describe` blocks.
- Both test suites must actually run: `pytest backend` and `npx vitest run` in `frontend/` (add `package.json` with `vitest` and `typescript` dev dependencies and a lockfile).

`expected_graph.json` follows the export shape in contract section 8, keyed by node keys, listing the CONTAINS, IMPORTS, CALLS, INHERITS, TESTS, HANDLES and CALLS_HTTP edges a perfect indexer would produce, and marking the deliberately unresolvable calls in a separate `"unresolvable"` list. `LABELS.md` explains every non-obvious label in one line, so the owner can review the labels quickly; the labels are only trusted after that review.

## Part 2: the SCIP oracle

- A runner (Python entry point under `eval/oracle/`) that, for a repo path, runs `scip-python` on Python code and `scip-typescript` on TypeScript/JavaScript code (installed globally from npm in the cloud environment; check with `--version` and print install instructions if missing), producing `.scip` files.
- A converter from SCIP to a reference list: for each occurrence of a function or method symbol inside another function's range, emit `(enclosing_definition_key, referenced_definition_key, line)`. Use the `scip` CLI's conversion or print commands, or decode the protobuf with the published SCIP schema; explain the choice. Map SCIP ranges to CodeAtlas keys by file path and definition span.
- Output: `oracle_<repo>_<sha12>.json` with the same edge shape, kind `calls`, resolution `"scip"`.

Note in the explainer what a SCIP reference is not: a reference is not always a call (passing a function as a value also counts), so the oracle is an upper bound for call recall.

## Part 3: the scorer

`python -m eval.oracle.score --predicted export.json --truth expected_graph.json` (or an oracle file) prints and saves:

- precision, recall and F1 per edge kind, per language, and per resolution level of the predicted edge
- a confidence calibration table: for predicted CALLS edges binned by confidence (0.0 to 0.3, 0.3 to 0.6, 0.6 to 0.9, 0.9 to 1.0), the share that are true
- the 20 worst false positives and false negatives with file and line, for debugging
- results as JSON in `eval/results/` with a timestamp

## Tests

Scorer on tiny hand-made predicted and truth files with known answers; calibration bins; key mapping from SCIP ranges on a two-file sample (commit a small `.scip`-derived JSON fixture so the test runs without the indexers); both fixture test suites pass.

## Done when

Fixture and labels committed; `pytest backend` and `vitest run` pass; the oracle produces a reference list for the fixture in the cloud session (report counts in the pull request); scorer tests pass; explainer written.

## Notes from T00 (read before starting)

- **The fixture's own dependencies belong to the fixture.** FastAPI (for the backend tests) goes in `eval/fixtures/polyglot_app/requirements.txt`; vitest and typescript go in its `package.json` with a lockfile. They are not CodeAtlas dependencies: do not add them to `pyproject.toml`. The no-new-dependencies rule in `CLAUDE.md` is about `pyproject.toml`.
- **The fixture never runs in CI.** The project's pytest collects only `tests/` and ruff skips `eval/fixtures`, so install the fixture's dependencies in your session, run `pytest backend` and `npx vitest run` there, and report the results in the pull request.
- **The oracle and scorer are project code.** Everything under `eval/oracle/` must pass `ruff check .`, and its unit tests go in `tests/eval/`, which CI runs.
- **SCIP indexers** were installed by the environment's setup script; check them with `--version` before use.

## Review of PR #10 (Oct 30)

**Verdict**: merge after fixes. **Fixes**: issue #17. Paste it into the T05 session; part 0 takes T15's commit off this branch, so the PR no longer depends on PR #9.

**The scip-python Windows bug came up here**, as you asked to be told. The SCIP runner has no platform check: on Windows it crashes with a raw `FileNotFoundError` (npm installs `scip-python.CMD`, which `subprocess` cannot start), and with the tools missing it advises `npm install`, which leads straight to the upstream crash. Issue #17 part 1 makes it refuse with a clear message, as decision D-10 requires. The scorer itself works on Windows.

**What the PR does**: a FastAPI + TypeScript fixture app (33 functions, 11 tests, 3 routes) with a hand-written answer key (`expected_graph.json`, 165 edges, explained in `LABELS.md`); a SCIP oracle that runs the two indexers, decodes their output with a small hand-written reader and turns references into `calls` edges; and a scorer giving precision, recall and F1 per kind, language and resolution, a calibration table and the 20 worst misses. Of T05's 5,781 added lines, 3,289 are generated (the npm lockfile, the oracle reference file, a sample score); about 2,500 are hand-written.

| Check | Result | Evidence |
| --- | --- | --- |
| Scope | WARN | T05's own 45 files are inside the brief; but the branch carries T15's whole commit (91 files) |
| Contract untouched | PASS | No diff in `models.py` or `indexer/adapter.py` |
| Tests | PASS | 269 passed (30 for the oracle and scorer). Fixture: `pytest backend` 6 passed, `vitest` 5 passed, `tsc --noEmit` clean |
| Lint | PASS | `ruff check .` clean |
| Mutation spot-check | PASS | 3 of 3 caught: bin edges, the unresolvable set-aside, innermost vs outermost scope |
| Explainer | PASS | Two worked examples and a "What a SCIP reference is not" section; nothing on Windows |
| Labels spot-check | 10/10 | 10 random labelled edges all match the source; the registry, `getattr` and `func(...)` calls are in "unresolvable" |
| Safety | PASS | Subprocesses: the two indexers, read-only `git rev-parse`, and the fixture's own suites in live tests only |
| Silent gaps | WARN | Module-level references dropped uncounted; the scorer ignores the oracle's `errors`, so a partial oracle scored 1.0/1.0 |
| Windows | FAIL | Crashes instead of refusing (must fix 1) |

**Oracle against the labels**: calls precision 0.953, recall 0.911 (41 right, 2 extra, 4 missed; the 4 are constructor calls the oracle cannot see).

**Must fix** (issue #17, parts 0 and 1)
1. `eval/oracle/run.py:145-168`, `:49-54`: refuse on Windows with a clear message (above).
2. The branch includes T15's commit; rebase it off.

**Should fix** (issue #17, parts 2 and 3)
1. The scorer drops the truth file's `errors` and both snapshots, so a result does not say what was measured or what was missing.
2. The converter drops module-level references uncounted, silently uses an empty prefix in one case, and crashes on a truncated `.scip` file.
3. The oracle file is named after the CodeAtlas repository's HEAD, so it goes stale with every commit, and stores an absolute `source` path.

**Your decisions** (the PR's twelve, then two from the review; write your answer next to each)

| # | Question | Recommendation |
| --- | --- | --- |
| 1 | Route key `routes.py::route:GET /api/users/{id}` | Accept; add it to the contract's identifiers table before T11 (D-15) |
| 2 | A decorator counts as a call from the decorated function | Accept; T01 must change to match (D-11, issue #13 part 2) |
| 3 | Constructor calls go to the `__init__` that runs, including an inherited one | Accept; the T06 brief says so |
| 4 | JSX `<UserCard/>` is a call | Accept; T02 already does this |
| 5 | TESTS edges only for direct calls to non-test functions | Accept |
| 6 | Imports through a barrel are labelled with the real definition | Accept; T07 must follow re-exports |
| 7 | No edge for module-level calls | Accept: the contract has CALLS only from functions and tests |
| 8 | `TestClient` calls count as CALLS_HTTP | Accept; list httpx and TestClient as clients in the T11 brief |
| 9 | Predictions outside the truth's scope are set aside, not counted as false positives | Accept, only with should fix 1 |
| 10 | Hand-written SCIP decoder (210 lines, tested, no dependency) | Accept |
| 11 | `label` and `scip` resolutions outside the enum | Accept: they appear only in truth files |
| 12 | Commit the oracle file | Accept, after should fix 3 |
| 13 | The labels contain `logged → logged.wrapper` (function contains function), which the contract's CONTAINS list does not allow | Add "Function → nested function" to the contract (D-14) |
| 14 | The `overall` row mixes edge kinds (oracle recall 0.248 overall, 0.911 for calls) | Read `by_kind` first; consider dropping `overall` |

**Try it yourself** (PowerShell, after `gh pr checkout 10`)

```powershell
python -m pytest tests/eval -q          # expect: 30 passed, 3 deselected
python -m eval.oracle.score --predicted eval\oracle\references\oracle_polyglot_app_061bf641daff.json --truth eval\fixtures\polyglot_app\expected_graph.json --out-dir $env:TEMP\ca-scores
```

The second command scores the SCIP oracle against your hand labels: the `calls` row shows precision 0.953, recall 0.911. After the fixes the oracle file has a new name; use whatever `eval\oracle\references` contains.

**Read these yourself**
- `eval/fixtures/polyglot_app/LABELS.md`, the CALLS and TESTS sections: T06 and T07 will be scored against these rules, and they count as truth only after you review them. This is the most important reading of the day.
- `eval/oracle/score.py:60-76` (`split_predicted`): decides what counts as wrong and what is not judged at all (question 9).
- `eval/oracle/convert.py:202-249`: how a SCIP mention becomes a caller-to-callee edge, and why the oracle is only an upper bound for call recall.
