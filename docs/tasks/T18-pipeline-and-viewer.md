# T18: Pipeline, `codeatlas index` and `codeatlas view`

**Wave**: 2 (first; the resolvers T06, T07 and T16 plug into it)
**Branch**: keep the one the cloud environment gives you

## Goal

Wave 1 built the parts; nothing joins them yet. This task builds the pipeline that turns a path or a GitHub URL into a stored, browsable graph, in one command:

```powershell
codeatlas index https://github.com/pallets/click
codeatlas view            # opens an HTML page of the graph in the browser
```

It also gives the resolvers (T06, T07, T16) and the linker (T11) one place to plug in, and gives every later task a one-line way to score the fixture.

## Files you may create or edit

- `src/codeatlas/indexer/pipeline/` (new package): the pipeline, CONTAINS edges, plugin registration, the index report
- `src/codeatlas/view/` (new package): the HTML viewer
- `src/codeatlas/cli.py`: add `index`, `view` and `export`; move the per-file parsing loop out of `scan` into the pipeline package and have `scan` call it (its output must not change)
- `scripts/score_fixture.py`
- `tests/pipeline/`, `tests/view/`, and `tests/test_cli.py` for the new commands
- `docs/explainers/pipeline.md` (the pipeline and the viewer together)

Do not edit the store, the adapters or the repository layer. If one of them gets in your way, work around it and note it in the pull request.

## Part 1: plugin registration (`indexer/pipeline/plugins.py`)

Two dictionaries in the same style as `DEEP_ADAPTERS`, empty in this task:

```python
RESOLVERS: dict[str, str] = {}  # name -> "module.path:ClassName"; T06, T07 and T16 add one line each
LINKERS: dict[str, str] = {}    # name -> "module.path:ClassName"; T11 adds one line
```

Each class is constructed with no arguments and satisfies the contract's `Resolver` or `Linker` protocol. A plugin that fails to import is reported (name and error) and skipped; it never stops an index.

## Part 2: `index_repository` (`indexer/pipeline/index.py`)

`index_repository(source: str, config: Config, db_path: Path, force: bool = False) -> IndexReport`. The steps, in order:

1. **Intake and discovery** as `scan` does today: `open_source`, `discover` with a `Deadline`, the snapshot id from the commit (or the content hash outside git).
2. **Existing snapshot**: if the store already has this snapshot id, return its saved report unless `force`, which calls `GraphStore.delete_snapshot` (added by T03's review fixes) and indexes again.
3. **Parse** every file through the registry, exactly as `scan` does. A file the deadline cuts off still gets its module node, with `attrs["skipped_reason"]`, and the snapshot records `max_seconds` in `limits_hit`.
4. **Record problems on the node** (decision D-13): copy each `ParseResult.errors` into its module node's `attrs["errors"]`. Two nodes with the same id in one file: keep the first, add an error naming the duplicate.
5. **Repository layer**: run `default_analyzers(config)` on the file records. Before writing, set each module node's `attrs["package_key"]` from the manifests analyzer's Package → Module CONTAINS edges.
6. **CONTAINS edges** (`indexer/pipeline/contains.py`), resolution `STRUCTURAL`, confidence 1.0, for every tier:
   - a node with `owner_key` is contained by its owner (Class → method);
   - otherwise, if its qualname has a `.` and the part before the last `.` is the qualname of another node in the same file, that node contains it (Function → nested function, decision D-14; Class → nested class);
   - otherwise the module contains it.
   A `#` right after a `.` is part of a name (a TypeScript private member, D-16), and a `#hash` suffix is not a separate level. TypeScript test qualnames (`A > b`) are contained by their module.
7. **Write** files, nodes, raw calls and the repository layer's nodes and edges.
8. **Resolve**: for each registered resolver, pass the `ParseResult`s whose language is in its `languages` and `store.symbol_index(snapshot_id)`. Catch each resolver's exceptions, record them in the report and continue. Report every language that has files but no resolver.
9. **Link**: the same for each registered linker; write the nodes it returns.
10. **External nodes** (decision D-19): an edge whose `dst_id` has the key form `::external:<dotted name>` points outside the repository. Create one EXTERNAL node per distinct key (name = the last dotted segment, language = the source node's language, path `""`), so every edge has both ends.
11. **Validate and write edges**: drop an edge whose source or target node does not exist, or whose confidence is outside (0, 1], and count each drop by reason in the report; never drop silently. Deduplicate identical (src, dst, kind) edges, keeping the highest confidence and the first line.
12. **Finish**: `mark_resolved_calls`, the final `limits_hit`, and the report.

Keep each step a small function so the explainer can walk through them one by one.

## Part 3: the index report

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

## Part 4: the commands

| Command | Does |
| --- | --- |
| `codeatlas index <path-or-url> [--db PATH] [--force]` | Runs the pipeline; prints a short summary in the style of `scan` (census, edges by kind and resolution, unresolved calls, problems) and the next command to run |
| `codeatlas view [--db PATH] [--snapshot ID] [--focus PATH_PREFIX] [--out FILE] [--no-open]` | Writes the HTML viewer for the latest snapshot (or the given one) and opens it with `webbrowser` |
| `codeatlas export [--db PATH] [--snapshot ID] --out FILE` | Writes the contract section 8 JSON, for the scorer |

The default database is `<data_dir>/codeatlas.db`.

`scripts/score_fixture.py`: indexes `eval/fixtures/polyglot_app` into a temporary database, exports it, runs `eval.oracle.score` against `expected_graph.json`, and prints the per-kind table. This is how T06 and T07 will measure themselves, so it must run in one command on Windows and Linux.

## Part 5: the viewer (`view/`)

One self-contained HTML file: the data embedded as JSON, the HTML, CSS and JavaScript in a Python module (no package-data changes to `pyproject.toml`). One JavaScript library from a pinned CDN URL is allowed for drawing the graph (for example cytoscape.js from cdnjs); if it fails to load, the page still shows everything as lists and says so. The page shows:

1. **Header**: repository, commit, when it was indexed, limits hit (highlighted when any).
2. **Census**: languages by tier with files, symbols, raw calls, the share of calls resolved, and errors.
3. **Packages**: packages with ecosystem and file count, and their DEPENDS_ON edges.
4. **Explorer**: a folder tree; selecting a file lists its symbols; selecting a symbol shows its signature, docstring, `path:line`, its incoming and outgoing edges grouped by kind with resolution and confidence, and its unresolved calls.
5. **Neighbourhood graph**: the selected file or symbol and its neighbours up to depth 2 (at most 150 nodes), edges styled by kind, faded by confidence.
6. **Problems**: files with errors or skip reasons, languages without a resolver, dropped edges.

For a large repository, cap the embedded data (for example 30,000 nodes) and say on the page what was left out and how to use `--focus` for a subfolder. No silent gaps here either.

## Tests

- The pipeline on a small multi-language repository built in the test (Python, TypeScript, a Go file, a README): every file has a module node, CONTAINS edges follow the three rules, parse errors land in `attrs["errors"]`, the report counts add up.
- A fake resolver registered through a monkeypatched `RESOLVERS` produces edges that are written; a resolver that raises is reported and the index still completes; a broken plugin path is reported.
- External nodes are created for `::external:` targets; a dangling edge is dropped and counted.
- Indexing twice returns the saved report; `force` re-indexes.
- `export` matches contract section 8; `view` writes a file whose embedded JSON parses and names the snapshot; nothing opens a browser or touches the network in tests.
- `scan` output is unchanged (its existing tests stay green).

## Done when

All tests pass on Linux and Windows CI. In the pull request, report `codeatlas index` and `codeatlas view` on this repository, on the fixture and on `https://github.com/pallets/click` (time, counts, problems), with a screenshot of the viewer if the session can take one (with a headless browser, if one is available; do not install one), and the output of `python scripts/score_fixture.py`. Before T06 and T07 merge, CALLS recall will be near zero; that is expected. The explainer covers the twelve steps with a worked example on a three-file repository.
