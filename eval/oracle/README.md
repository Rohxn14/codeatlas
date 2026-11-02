# Oracle

Ground truth for the indexer's graph, and the scorer that compares a CodeAtlas graph export
with it. Everything is in the graph export shape of `docs/contract.md` section 8 and is
compared by key. See `docs/explainers/graph-eval.md`.

| File | Role |
| --- | --- |
| `scip.py` | Decodes a `.scip` index using the standard library only |
| `convert.py` | Turns SCIP occurrences into `(caller key, callee key, line)` references |
| `run.py` | `python -m eval.oracle.run REPO [--nodes graph.json]`: runs `scip-python` and `scip-typescript` and writes `references/oracle_<repo>_<sha12>.json` |
| `graph.py` | Reads export, expected and oracle files |
| `score.py` | `python -m eval.oracle.score --predicted export.json --truth expected_graph.json`: precision, recall, F1, calibration and worst misses, saved to `eval/results/` |

Hand-labelled truth for the fixture lives in `eval/fixtures/polyglot_app/expected_graph.json`.

**Linux only for `run.py`** (decision D-10). scip-python crashes on Windows: it builds a
regular expression from `path.sep`, and a lone backslash is not a valid pattern (the
upstream fix, scip-python PR #211, was closed unmerged). On Windows `run.py` prints this
and exits with status 2. Run it in a cloud session, in CI or in WSL. The scorer, and the
committed oracle file in `references/`, work on Windows.

**File names.** For a repository's top level, `<sha12>` is its HEAD commit. For a folder
inside a repository, such as the fixture, it is the folder's own tree hash
(`git rev-parse HEAD:<folder>`), so the file is renamed only when the folder's files
change, and `source` is the folder's repo-relative path.

**Partial truth.** An oracle file lists failed indexers under `errors` and the references
it could not turn into edges under `skipped`. The scorer copies the truth's errors and
both snapshots into its result under `measured`, and prints a WARNING line when the truth
is partial or the prediction hit an indexing limit.
