# T18: Pipeline, `codeatlas index` and `codeatlas view`

**Wave**: 2 (parallel with T06, T07, T16, T08, T09, T10)
**Branch**: keep the one the cloud environment gives you

## Goal

The pipeline's core already exists (`src/codeatlas/indexer/pipeline/`, read `docs/explainers/pipeline.md` first): `build_graph(source, store)` parses, adds containment and the repository layer, runs the registered resolvers and linkers, and writes one snapshot. What is missing is everything a person uses: one command to index, a report of what happened, and a page to look at the graph:

```powershell
codeatlas index https://github.com/pallets/click
codeatlas view            # opens an HTML page of the graph in the browser
```

## Files you may create or edit

- `src/codeatlas/indexer/pipeline/` (new modules, and additive changes to `build.py`; keep `build_graph`'s signature and behaviour, since T06, T07, T16, T08, T09 and T10 call it in parallel)
- `src/codeatlas/view/` (new package): the HTML viewer
- `src/codeatlas/cli.py`: add `index`, `view` and `export`
- `tests/pipeline/`, `tests/view/`, and `tests/test_cli.py` for the new commands
- `docs/explainers/pipeline.md` (extend it with the report, the commands and the viewer)

Do not edit `plugins.py` (its entries are fixed ahead of Wave 2), the store, the adapters or the repository layer.

## Part 1: `index_repository`

`index_repository(source: str, config: Config, db_path: Path, force: bool = False) -> IndexReport` in `indexer/pipeline/index.py`:

- open the store at `db_path` (default `<data_dir>/codeatlas.db`, see `default_db_path`);
- if the snapshot already exists, return its saved report unless `force`, which re-indexes with `build_graph(..., replace_existing=True)`;
- otherwise call `build_graph`, time each step (add timing to `BuildResult` if you need it, without changing what it already holds), and build the report.

## Part 2: the index report

`IndexReport` is a dataclass with `to_dict()`, saved as JSON at `<data_dir>/reports/<snapshot id with @ and / replaced by _>.json`. The acceptance suite (T10) will read this file, so keep the field names stable and list them in the explainer:

| Field | Content |
| --- | --- |
| `snapshot` | The contract section 8 snapshot object |
| `seconds` | Per step: intake, discover, parse, repo_layer, write, resolve, link, total |
| `files` | Total, by tier, by language, skipped with reasons grouped |
| `nodes` | By kind |
| `edges` | By kind, by resolution, dropped by reason |
| `raw_calls` | Total, resolved, unresolved, unresolved by language |
| `problems` | Files with errors, plugin import failures, resolver and linker exceptions, languages without a resolver |
| `repo_layer` | The output of T15's `summarize` |

## Part 3: the commands

| Command | Does |
| --- | --- |
| `codeatlas index <path-or-url> [--db PATH] [--force]` | Runs the pipeline; prints a short summary in the style of `scan` (census, edges by kind and resolution, unresolved calls, problems) and the next command to run |
| `codeatlas view [--db PATH] [--snapshot ID] [--focus PATH_PREFIX] [--out FILE] [--no-open]` | Writes the HTML viewer for the latest snapshot (or the given one) and opens it with `webbrowser` |
| `codeatlas export [--db PATH] [--snapshot ID] --out FILE` | Writes the contract section 8 JSON, for the scorer |

The default database is `<data_dir>/codeatlas.db`.

## Part 4: the viewer (`view/`)

One self-contained HTML file: the data embedded as JSON, the HTML, CSS and JavaScript in a Python module (no package-data changes to `pyproject.toml`). One JavaScript library from a pinned CDN URL is allowed for drawing the graph (for example cytoscape.js from cdnjs); if it fails to load, the page still shows everything as lists and says so. The page shows:

1. **Header**: repository, commit, when it was indexed, limits hit (highlighted when any).
2. **Census**: languages by tier with files, symbols, raw calls, the share of calls resolved, and errors.
3. **Packages**: packages with ecosystem and file count, and their DEPENDS_ON edges.
4. **Explorer**: a folder tree; selecting a file lists its symbols; selecting a symbol shows its signature, docstring, `path:line`, its incoming and outgoing edges grouped by kind with resolution and confidence, and its unresolved calls.
5. **Neighbourhood graph**: the selected file or symbol and its neighbours up to depth 2 (at most 150 nodes), edges styled by kind, faded by confidence.
6. **Problems**: files with errors or skip reasons, languages without a resolver, dropped edges.

For a large repository, cap the embedded data (for example 30,000 nodes) and say on the page what was left out and how to use `--focus` for a subfolder. No silent gaps here either.

## Tests

- `index_repository` on a small repository built in the test: the report's counts match the store; indexing twice returns the saved report; `force` re-indexes.
- The report is written where the explainer says and parses as JSON with the listed fields.
- `export` matches contract section 8; `view` writes a file whose embedded JSON parses and names the snapshot; `--focus` limits the embedded files; the size cap is reported on the page.
- Nothing opens a browser or touches the network in tests; `scan`'s tests stay green.

## Done when

All tests pass on Linux and Windows CI. In the pull request, report `codeatlas index` and `codeatlas view` on this repository, on the fixture and on `https://github.com/pallets/click` (time, counts, problems), with a screenshot of the viewer if the session can take one (with a headless browser, if one is available; do not install one), and the output of `python scripts/score_fixture.py`. Before T06 and T07 merge, CALLS recall will be near zero; that is expected. The explainer gains the report fields, the three commands and how the viewer is built.
