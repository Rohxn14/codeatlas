# Graph evaluation: fixture, SCIP oracle and scorer

Modules: `eval/fixtures/polyglot_app/` (the app, `expected_graph.json`, `LABELS.md`) and
`eval/oracle/` (`scip.py`, `convert.py`, `run.py`, `graph.py`, `score.py`).

## What

Three tools measure how good the indexer's graph is:

| Part | Gives |
| --- | --- |
| **Polyglot fixture** | A small FastAPI and TypeScript app (33 functions, 11 tests, 3 routes) with a hand-labelled `expected_graph.json`: every CONTAINS, IMPORTS, CALLS, INHERITS, TESTS, HANDLES and CALLS_HTTP edge a perfect indexer would find, plus an `unresolvable` list of the call sites no static tool can resolve |
| **SCIP oracle** | Ground truth for *any* repository: it runs the compiler-grade indexers `scip-python` and `scip-typescript`, then converts their output into CALLS-shaped edges keyed like CodeAtlas |
| **Scorer** | Compares a CodeAtlas export with either kind of truth. It reports precision, recall and F1 per edge kind, language and resolution, a confidence calibration table, and the 20 worst false positives and false negatives. Results are saved to `eval/results/` |

## Why

- **Hand labels and an oracle are both needed.** The fixture covers every edge kind, but it
  is tiny. The oracle covers real repositories, but only calls, and only as an upper bound
  (see below). Each one covers a gap in the other.
- **A deliberately tricky fixture.** It has an aliased import, `super()`, an inherited
  method, a decorator, a registry call, `getattr`, a barrel re-export, an `axios` base URL,
  a template-literal URL, JSX, nested `describe` blocks and functions with the same name in
  two files. Each one is a known way for a resolver to fail. Both test suites run (`pytest
  backend`, `npx vitest run`), so the app is real code, not pseudo-code.
- **Decoding SCIP by hand instead of using the `scip` CLI or `protobuf`.** The `scip` CLI is
  not installed in the environment, and `protobuf` is not a CodeAtlas dependency (it is only
  pulled in indirectly by `onnxruntime`). The protobuf wire format is simple: each field is
  a tag (field number × 8 + wire type) followed by a varint or a length-prefixed blob. The
  oracle needs just 10 fields, so `scip.py` decodes them in about 100 lines of
  standard-library code. Rejected: generating `scip_pb2.py` (it would add a generated
  file and a hidden dependency) and `scip print --json` (one more tool to install).
- **Caller found by span, callee by symbol.** SCIP gives every definition an
  `enclosing_range` (its whole body), so the caller of a reference is the innermost
  definition whose body holds that line. SCIP symbols carry the qualname
  (`UserService#create_user().`), so the callee's key is `path::UserService.create_user`.
  A CodeAtlas node list (`--nodes`) adds the spans SCIP cannot know about. Vitest's
  `it("...")` callbacks are anonymous to SCIP, but they are TEST nodes in CodeAtlas.
- **Scope before scoring.** The truth says nothing about what it does not list. A predicted
  edge into `requests` or a package node is neither right nor wrong, so the scorer sets it
  aside and counts it, rather than calling it a false positive. Predictions at an
  `unresolvable` call site are guesses, so they are reported separately.
- **Line is not part of edge identity.** An edge is `(src_key, dst_key, kind)`, because the
  graph stores one CALLS edge per caller and callee pair. Lines are kept for debugging.
- **Per-resolution recall cannot be split exactly.** A missed edge has no resolution, so the
  scorer reports each resolution's precision and its `recall_share`: its true positives as
  a share of all truth edges of the same kinds.

### What a SCIP reference is not

A SCIP reference is any mention of a symbol, so it is not always a call. Passing a function
as a value counts, and so do returning it (`return wrapper` in `logged`) and comparing it
(`toBe(UserCard)`). Constructor calls point at the class, not at `__init__`, so the oracle
misses them. Arrow functions stored in a `const` are *term* symbols, not methods, so the
converter misses calls to them too. The oracle is therefore an **upper bound for call
recall**, not exact truth. On the fixture it agrees with the hand labels on 41 of 45 CALLS
edges. It misses the 4 constructor calls and adds 2 references that are not calls.

## How

**Oracle**, step by step (`python -m eval.oracle.run eval/fixtures/polyglot_app --nodes
eval/fixtures/polyglot_app/expected_graph.json`). On Windows the runner stops at once with
a message: scip-python cannot run there (decision D-10; upstream PR #211 was closed
unmerged), so the oracle is built in a cloud session, CI or WSL, and the committed file is
used on Windows.

1. List the source files, skipping `node_modules`, virtual environments and hidden folders.
2. If there is Python, run `scip-python index --project-name <repo> --project-version
   <sha12>`. Without a version it crashes on Python 3.13 (`reading 'indexOf'`).
3. Run `scip-typescript index` once per `tsconfig.json` folder, or once at the root with
   `--infer-tsconfig` when there is none. Its paths are relative to that folder, so the
   index's `project_root` gives the prefix (`frontend/`).
4. Decode each `.scip` file. Collect the definitions of functions, methods and classes,
   keyed `path::qualname`.
5. For every reference to an in-repo function, find the innermost caller scope. Emit one
   edge per caller and callee pair, at the first line it appears. References at module
   level (imports, re-exports, `HANDLERS = {...}`) have no caller and make no edge; they
   are counted under `skipped` in the output (19 for the fixture), so nothing is lost
   without a trace.

Worked example from the fixture. `backend/user_repo.py` holds this occurrence:

```
range [8, 16, 8, 20]  symbol "... `backend.repo`/Repo#save()."  roles 8 (read)
```

SCIP lines are 0-based, so this is line 9. The definitions in this file include
`UserRepo#save().` with enclosing range lines 5 to 8, which are lines 6 to 9. The class
`UserRepo#` is not a scope. So the caller is `backend/user_repo.py::UserRepo.save`.
The symbol's own definition is in `backend/repo.py`, so the callee is
`backend/repo.py::Repo.save`. The result is the edge
`UserRepo.save → Repo.save, line 9, resolution "scip"`, which matches the hand label.

**Scorer** (`python -m eval.oracle.score --predicted export.json --truth expected_graph.json`):

1. Read both files and deduplicate edges by triple, keeping the most confident copy.
2. Set aside predicted edges whose kind the truth never uses, whose endpoints are not
   truth nodes, or that start at an unresolvable call site.
3. Count true positives (triples in both), false positives and false negatives. Group the
   counts by kind, by the source node's language and by predicted resolution.
4. Bin predicted CALLS by confidence: `[0, 0.3)`, `[0.3, 0.6)`, `[0.6, 0.9)` and
   `[0.9, 1.0]`. For each bin, report the share that is true. A well-calibrated
   `name_guess` at 0.25 should be right about a quarter of the time.
5. List the false positives with the highest confidence first (the most misleading ones),
   and the false negatives by kind, file and line. Print the tables, then save the JSON to
   `eval/results/graph_score_<truth>_<UTC timestamp>.json`.

A small example. The truth has `f→g`, `f→h` and `g→h`. The prediction has `f→g` (direct,
1.0), `f→h` (import_scoped, 0.5) and `g→f` (name_guess, 0.25). That gives TP 2, FP 1 and
FN 1, so precision and recall are both 0.667. In the calibration table, the `[0, 0.3)` bin
holds 1 edge with share true 0, and the `[0.3, 0.6)` bin holds 1 edge with share true 1.

## Where

- **Contract**: reads and writes the graph export shape of `docs/contract.md` section 8.
  It uses node keys (`make_key` format: `path::qualname`, with ` > ` for TypeScript
  tests), the `EdgeKind` values as strings and the `Resolution` values. Two values are
  added outside the enum and appear only in truth files: `"label"` for hand labels and
  `"scip"` for oracle edges.
- **T03 (store)** writes the export this scorer reads. **T01, T02 and T06 (resolvers)** and
  **T07 (linker)** are what it measures. The `unresolvable` list and the calibration bins
  check the confidence rules in contract section 5.
- **Acceptance suite**: `run.py` works on any cloned repository, so each benchmark repo can
  get an oracle file next to its CodeAtlas export.
- **Safety**: the SCIP indexers are static analysers. The runner never installs packages in
  the indexed repository and never runs its code. Only the fixture's own test suites are
  run, by hand or under `pytest -m live`.
