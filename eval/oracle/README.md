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
