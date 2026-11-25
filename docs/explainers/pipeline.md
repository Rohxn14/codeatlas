# Pipeline (core)

## What

`build_graph(source, store)` turns a folder or a repository URL into one stored snapshot: every file as a module node, every symbol the adapters found, containment, the repository layer (packages, test pairings, co-change), and whatever the registered resolvers and linkers add. `parse_source` is its first half and is what `codeatlas scan` uses. `scripts/score_fixture.py` runs the whole thing on the polyglot fixture and scores it against the hand labels.

T18 adds `index_repository` (build once, save a report), the commands `codeatlas index`, `view` and `export`, and the HTML viewer. The resolvers (T06, T07, T16) and the linker (T11) plug in through `plugins.py`.

## Why

- **One place joins the parts.** Wave 1 built adapters, a store and a repository layer that never met. Without a pipeline nobody could see a graph, and no resolver could measure itself.
- **Plugins by dictionary, like `DEEP_ADAPTERS`.** `RESOLVERS` and `LINKERS` map a name to `"module:Class"`. Each Wave 2 task adds one line, so parallel sessions never edit the same line, and a plugin that fails to import is reported, not fatal. Rejected: entry points in `pyproject.toml` (sessions may not edit it) and a hard-coded list (every task would edit the same function).
- **The pipeline owns containment.** The contract says so, and doing it once means a method sits inside its class whichever tier parsed it. Rejected: each adapter emitting CONTAINS (three copies of one rule, and the structural tier would differ).
- **Problems live on the module node (D-13).** The store has no table for parse errors, and every file has a module node, so `attrs["errors"]` needs no schema change and shows up wherever the file does.
- **External nodes are made here (D-19).** The contract's `Resolver.resolve` returns edges only, so a resolver points an edge at the reserved key `::external:requests.get` and the pipeline creates one EXTERNAL node per key.
- **Nothing is dropped silently.** An edge with a missing end or a confidence outside (0, 1] is dropped and counted by reason in `BuildResult.edges_dropped`; a failed resolver or analyzer is named in `problems`; languages with symbols but no resolver are listed.

## How

1. `parse_source`: intake, discovery with the time limit, one adapter per file. A file the deadline cuts off still gets a module node with `skipped_reason`.
2. `_record_problems`: copy `ParseResult.errors` into the module node's `attrs["errors"]`; of two nodes with the same id, keep the first and add an error.
3. `_repository_layer`: run `default_analyzers`; then `_with_package_keys` sets each module's `attrs["package_key"]` from the Package → Module CONTAINS edges.
4. `contains_edges` (`contains.py`): a node with `owner_key` is inside its owner; else the part of its qualname before the last `.` names its parent in the same file (Function → nested function, D-14); else the module. A `#` right after `.` is part of a name (D-16) and a trailing `#hash` is not a level.
5. Write the snapshot, files, nodes and raw calls.
6. `_run_resolvers`: each resolver gets the parse results of its `languages` and `store.symbol_index(...)`. Then `_run_linkers`.
7. `_external_nodes`: one EXTERNAL node per `::external:` target.
8. `_valid`: drop and count bad edges; merge repeats of (source, target, kind), keeping the highest confidence and the first line. Write, then `mark_resolved_calls`.

Worked example, on a two-file repository: `app/service.py` defines `logged` with a nested `wrapper`, and `class Service` with `save`, which calls `helper()`; `README.md` is text. Parsing gives module nodes for both files and four symbols. Containment gives `service.py:: → logged`, `logged → logged.wrapper`, `service.py:: → Service`, `Service → Service.save`. The manifests analyzer finds no manifest, so an implicit package contains both modules, and each module's `package_key` names it. With no resolver registered, `helper()` stays a raw call, and `python` is listed under languages without a resolver. A resolver returning `Service.save → ::external:lib.helper` would make one EXTERNAL node named `helper`, and `mark_resolved_calls` would then count the call as resolved.

On the fixture today: CONTAINS precision and recall 1.0 (53 of 53), TESTS by naming convention 4 of 19, no CALLS or IMPORTS until T06 and T07 merge.

## The index report (T18)

`index_repository(source, config, db_path, force=False)` opens the store, calls `build_graph`, and counts what the *store* holds (so the report cannot disagree with the database). If `build_graph` raises `AlreadyIndexed` (a `ValueError` subclass, same message as before), the saved report is returned; `force` passes `replace_existing=True`. The snapshot id is only known after parsing (`build_graph` checks the store after `parse_source`), so a repeat run still parses every file before it finds the saved report; splitting intake out so the check comes first is a later improvement. The report also lists the folders discovery never entered (`files.not_entered`), such as `node_modules/`, which have no nodes at all. If the report file was deleted, the commit is rebuilt to recreate it.

It is saved as `<data_dir>/reports/<snapshot id with @ and / replaced by _>.json`. The acceptance suite (T10) reads it, so these names are stable:

| Field | Content |
| --- | --- |
| `snapshot` | contract section 8 snapshot object |
| `seconds` | `intake`, `discover`, `parse`, `repo_layer`, `write`, `resolve`, `link`, `total` |
| `files` | `total`, `by_tier` (the tier that parsed it), `by_language`, `skipped` (`total`, `by_reason`) |
| `nodes` | `total`, `by_kind` |
| `edges` | `total`, `by_kind`, `by_resolution`, `dropped` (reason to count) |
| `raw_calls` | `total`, `resolved`, `unresolved`, `unresolved_by_language` |
| `problems` | `files_with_errors` (path, errors), `plugin_and_resolver_failures`, `languages_without_resolver` |
| `repo_layer` | the output of `repo.summarize` |
| `embeddings` | `model`, `symbols`, `seconds`; or `model`, `error` when the model could not run; empty when none were asked for (since Nov 25; a report saved before then loads with it empty) |

Timing lives in `BuildResult.seconds` (and `Parsed.seconds` for the first three steps); `write` includes the final edge write.

## The commands

- `codeatlas index <path-or-url> [--db PATH] [--force]`: runs the pipeline, prints a summary like `scan` and `Next: codeatlas view`.
- `codeatlas view [--db PATH] [--snapshot ID] [--focus PATH_PREFIX] [--out FILE] [--no-open]`: writes `<data_dir>/view.html` (or `--out`) for the latest snapshot and opens it with `webbrowser` unless `--no-open`.
- `codeatlas export [--db PATH] [--snapshot ID] --out FILE`: `GraphStore.export_json`, the contract section 8 JSON.

The default database is `<data_dir>/codeatlas.db`. `view` and `export` fail with a clear message if there is no database or snapshot. The latest snapshot is the newest `indexed_at` over all repositories in the database.

## The viewer (`view/`)

`view/data.py` reads the store and builds one JSON object: snapshot, census (computed over the whole snapshot), packages with `DEPENDS_ON`, files, nodes, edges (as indexes into the node list), unresolved calls, problems, and `omitted`. `view/page.py` embeds it in one HTML string with its own CSS and JavaScript; `<` is escaped as `\u003c` so repository text cannot close the data tag, and the script uses `textContent` only, since names and docstrings are untrusted. cytoscape.js 3.30.2 from cdnjs draws the neighbourhood (depth 2, at most 150 nodes, edges coloured by kind and faded by confidence). If it does not load, the page says so and the explorer lists carry the same edges.

Size cap: at most 30,000 nodes. Path-less nodes (packages, externals, routes) go in first, then whole files in path order until the cap, so a file is never half shown. Edges need both ends shown. What was left out is counted in `omitted` and shown in a banner with the `--focus <folder>` hint; `--focus` keeps files under one prefix. Unresolved calls are capped at 20,000 and counted the same way.

## Where

- Reads: `indexer/intake.py`, `indexer/discover.py`, `indexer/registry.py` (adapters), `repo/` (`default_analyzers`).
- Writes: `store/` (`GraphStore`), and reads back `symbol_index` for resolvers.
- Contract types: `ParseResult`, `Node`, `Edge`, `Snapshot`, `FileRecord`, the `Resolver` and `Linker` protocols, `NodeKind.EXTERNAL`, `EdgeKind.CONTAINS`.
- Also reads: `repo.summarize` (report), `GraphStore.export_json` (export).
- Used by: `codeatlas index`, `view`, `export`, `codeatlas scan` (parsing only), `scripts/score_fixture.py`, and in Wave 2 the `index` command (T18), every resolver's measurement, search (T08), the agent (T09) and the eval harness (T10).
