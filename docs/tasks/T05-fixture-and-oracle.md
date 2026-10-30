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
