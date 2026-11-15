# The command line (`codeatlas`)

## What

One `codeatlas` command reaches everything the project can do. `scan`, `index`, `view`
and `export` build and show the map; `search`, `ask`, `impact`, `tests` and `mcp` query it.
The query commands are thin front ends: they open the store, pick a snapshot, call one
existing module (`search/hybrid.py`, `agent/loop.py`, `impact/engine.py`,
`agent/mcp_server.py`) and print the result as text or, with `--json`, as one JSON object.
`view --impact DIFF` adds an impact section to the HTML page. `serve` starts the local
web app (`web-app.md`); its packages are optional, so it imports them only when it runs.

## Why

- **One front end, no new logic.** Every number the CLI prints comes from a module that
  has its own tests and evaluation. The CLI only turns arguments into calls and results
  into lines, so a bug in ranking is never a CLI bug. The old entry points
  (`python -m codeatlas.search`, `python -m codeatlas.agent`) are kept unchanged.
- **The same `--db` default as `index`.** `<data_dir>/codeatlas.db`, so `index` then
  `search` works with no flags. (`python -m codeatlas.agent` defaults to
  `codeatlas.sqlite`; it was left alone, since the brief says not to change `agent/`.)
- **Four ways to give a change, exactly one at a time.** `--diff FILE`, `--diff -`,
  `--git REV`, `--files`. argparse's mutually exclusive group rejects none or two
  (exit 2), so a forgotten flag never means "an empty change".
- **`--git` runs only git.** `git -C <root> -c core.fsmonitor=false diff --relative --no-color --no-ext-diff --no-textconv REV --`.
  Before that it compares `git rev-parse HEAD` with the snapshot's commit and exits 2 if
  the checkout has moved, because `git diff REV` compares with the working tree.
  `--no-ext-diff`, `--no-textconv` and `core.fsmonitor=false` stop configured programs from running, and
  `--relative` keeps paths relative to the indexed folder when that folder sits inside a
  bigger repository (as `eval/fixtures/polyglot_app` does). The root is found the way the
  agent's tools find it (`ToolContext.repo_root`): the local source folder, or the clone of
  a URL. Rejected: reading the diff with a git library (a new dependency) and diffing
  stored file hashes (the store does not keep old file contents).
- **`ask` checks for a key before anything else.** Without `GROQ_API_KEY` or
  `GEMINI_API_KEY`, the providers would retry with a placeholder key and fail slowly. One
  line naming both variables and exit 2 is faster and clearer. A provider failure after
  that is exit 1, as in `python -m codeatlas.agent`.
- **One evidence line per target.** The best evidence is the reason a target ranks where
  it does; the rest are in `--json`. Hops print as `a <-calls 0.9- b`: the arrow points the
  way the edge points in code (b calls a), while the path reads from the change outwards.
- **The skipped share uses the evaluation's own pool** (`impact.evaluate.all_test_files`),
  so the number the CLI prints is the one the benchmark reports.

## How

`main` parses the arguments, loads the config, and looks the command up in `_RUNNERS`.
Every runner raises `ValueError`, `KeyError` or `OSError` for a user error, and `main`
turns those into `codeatlas: <message>` and exit 2.

`impact` and `tests` share `_impact_result`:

1. `_open_store`: the database (or "run `codeatlas index` first") and the snapshot (the
   newest by `indexed_at` unless `--snapshot`).
2. `read_changes`: `--files` becomes one whole-file `Change` per path, with `\` turned into
   `/` and a leading `./` removed; the other inputs become text for `parse_diff`.
3. `ImpactConfig(depth, decay)` from the flags or the defaults (4 and 0.8); a decay outside
   (0, 1) is the config's own `ValueError`.
4. `ImpactEngine(...).impact(changes)`.

Then `impact` prints the targets and `tests` prints the test picks, both cut at `--top`.
`tests` adds the files at or above `ImpactConfig.test_threshold` (0.3) and
`skipped = 1 - |selected ∩ all test files| / |all test files|`.

Worked example (the test repository in `tests/test_cli_commands.py`): `shop/repo.py`
holds `Repo.save`; `shop/service.py::create` calls it; `tests/test_service.py::test_create`
calls `create`; `tests/test_other.py` touches neither. The second commit edits line 3 of
`repo.py`.

```
codeatlas tests --git HEAD~1
```

`git diff HEAD~1` gives a hunk `@@ -1,3 +1,3 @@`; `parse_diff` returns
`Change("shop/repo.py", ((1, 3),))`, which maps to `Repo` and `Repo.save`.
`create` calls `save` with confidence 0.9: 0.9 × 0.8 = 0.72 after one hop. `test_create`
calls `create` at 1.0: 0.72 × 0.8 = 0.576, printed as
`graph 0.576: shop/repo.py::Repo.save <-calls 0.9- shop/service.py::create <-calls 1- tests/test_service.py::test_create`.
`tests/test_service.py` is above 0.3, `tests/test_other.py` is not, so the summary line is
`test files to run (score >= 0.3): 1 of 2; skipped share 50%`.

`view --impact DIFF` runs the same engine on the diff and stores
`view.data.impact_block(result)` under `data["impact"]`: the changed keys, the top 30
targets with score and best signal, and the warnings. The page shows them in a section at
the top, links each key that is on the page to the explorer, and colours changed nodes red
and targets orange in the neighbourhood graph.

## Where

- **Reads**: `GraphStore` (`store/`), the snapshot via `latest_snapshot_id` (`view/data.py`).
- **Calls**: `HybridSearch` and `build_embeddings` (`search/`), `EmbeddingClient` and
  `LLMClient` (`llm/`), `ask` (`agent/loop.py`), `ToolSet` and `ToolContext.repo_root`
  (`agent/tools.py`), `serve_stdio` (`agent/mcp_server.py`), `parse_diff`, `ImpactEngine`
  and `all_test_files` (`impact/`).
- **Contract types**: `Snapshot`, `Node` (`kind`, `key`, `path`, `span`) from
  `codeatlas.models`; the impact engine's `Change`, `ImpactConfig`, `ImpactResult`,
  `Target`, `TestPick`, `Evidence` and `Hop` from `impact/models.py`.
- **Tests**: `tests/test_cli_commands.py` (the query commands, on a two-commit repository
  built in the test, LLM mocked) and `tests/test_cli.py`, `tests/view/` (the older ones).
