# Start here: how to read CodeAtlas

CodeAtlas was built fast, in four waves of cloud sessions (Oct 30 to Nov 4, 2026). About
17,600 lines of library code and 2,900 lines of evaluation code now work, are tested and
are measured. This folder is how you get all of it into your own head. Read this page
first; it tells you what to read, in what order, and how.

## What is in `docs/`

| Path | What it is | Use it for |
| --- | --- | --- |
| `contract.md` | Every shared type: nodes, edges, keys, confidence levels, the adapter and resolver interfaces | The vocabulary. Read it first and come back often |
| `decisions.md` | Every design decision, with the reason. D-11 to D-23 are waiting for your yes or no | Answering "why is it like this?" |
| `explainers/` | One per module: **What**, **Why**, **How** (with a worked example), **Where** | Learning each module. Always read before the code |
| `tasks/` | The briefs the cloud sessions were given, each with a review at the end | History: what was asked, and what the review found. Not instructions for new work |
| `plans/` | The plans some sessions wrote before building | Seeing how a design was chosen |
| `roadmap.md` | Where the project stands, what is open, the decisions waiting for you, and the deployment direction | Deciding what to do next |
| `demo.md` | A real end-to-end run on a public repository | Seeing the whole thing work |
| `learning-log.md` | Your notes, four lines per module | Interviews and the project write-up |
| `history/` | Day and wave plans, and the cloud playbook | Only if you want the story of how it was built |

## How to study one module (about 1 to 2 hours each)

1. **Explainer.** Read `docs/explainers/<module>.md`. Close it and say the What, Why, How
   and Where out loud. Whatever you cannot say is your first question.
2. **Run it.** Index the fixture and look at what this module produced:
   `codeatlas index eval/fixtures/polyglot_app`, then `codeatlas view` or
   `codeatlas export --out graph.json`.
3. **Code.** Open the folder from the table below. Start from the one public entry point
   and follow calls inward. Do not read every helper; read the ones the explainer named.
4. **Tests.** Read two or three tests. A test is a small, exact example of what the code
   promises. Break one line of the code on purpose and watch which test fails.
5. **Brief and review.** Read `docs/tasks/Txx-*.md`. The brief is what was asked; the
   review at its end is what was wrong and what was fixed. The gap between the two is
   where the best interview stories are.
6. **Log it.** Four lines in `learning-log.md`: learned, would change, still unclear, and
   one line about working with the agent.
7. **Decide.** If the module has a decision waiting in `decisions.md`, answer it now,
   while it is fresh.

Ask Claude anything at any step. In a local session: "explain `_in_scope` in
`structural/resolver.py` like I'm new to it", or "why does the store keep raw calls?".

## The reading order: follow the data

The order follows one repository through the system, from a folder on disk to an answer.
Each step uses what the step before it produced.

| # | Module | Explainer | Code (`src/codeatlas/` unless noted) | Lines | Brief |
| --- | --- | --- | --- | --- | --- |
| 0 | The vocabulary | `contract.md` | `models.py`, `indexer/adapter.py` | 280 | |
| 1 | Intake and discovery: a folder or URL becomes a list of files with languages and tiers | `intake-and-discovery.md` | `indexer/intake.py`, `discover.py`, `registry.py`, `config.py` | 820 | T00 |
| 2 | The tags tier: any tree-sitter language becomes definitions and calls | `tags-tier.md` | `indexer/generic/` | 610 | T00, T21 |
| 3 | The repository layer: manifests, packages, test conventions, co-change from git | `repository-layer.md` | `repo/` | 2,280 | T15 |
| 4 | The deep Python adapter | `python-adapter.md` | `indexer/languages/python/` (not `resolver/`) | 890 | T01 |
| 5 | The deep TypeScript/JavaScript adapter | `typescript-adapter.md` | `indexer/languages/typescript/` (not `resolver/`) | 1,500 | T02 |
| 6 | The store: SQLite tables, full-text search, the graph view | `store.md` | `store/` | 860 | T03 |
| 7 | The pipeline: one build from start to end, the report and the viewer | `pipeline.md` | `indexer/pipeline/`, `view/` | 1,260 | T18 |
| 8 | The Python resolver: raw names become edges with confidence | `python-resolver.md` | `indexer/languages/python/resolver/` | 1,010 | T06 |
| 9 | The TypeScript resolver, with typed receivers | `typescript-resolver.md` | `indexer/languages/typescript/resolver/` | 1,500 | T07, T20 |
| 10 | The structural tier: one resolver, a small profile per language | `structural-tier.md` | `indexer/structural/`, `indexer/queries/` | 1,850 | T16, T17a, T17b, T17f |
| 11 | The HTTP linker: client calls meet server routes across languages | `http-linker.md` | `indexer/linker/` | 520 | T11, T11f |
| 12 | The LLM layer: Groq, Gemini, the record-and-replay cache, embeddings | `llm-layer.md` | `llm/` | 1,140 | T04 |
| 13 | Hybrid search | `search.md` | `search/` | 340 | T08 |
| 14 | The agent and the MCP server | `agent.md` | `agent/` | 1,060 | T09 |
| 15 | The impact engine: what a change breaks, which tests to run | `impact.md` | `impact/` | 1,020 | T12, T12f |
| 16 | The command line | `cli.md` | `cli.py` | 700 | T19 |
| 17 | Measuring it: the fixture, the oracle, the suite, mutants, co-change | `graph-eval.md`, `eval-harness.md` | `eval/`, `scripts/score_fixture.py` | 2,850 | T05, T10 |

At one module a day, that is about three weeks. Steps 8, 10 and 15 are the deep ones:
they hold most of the design decisions, and step 15 is the module you plan to rewrite.

## One build, traced through the code

When you run `codeatlas index eval/fixtures/polyglot_app`, this happens:

1. `cli.py` `_run_index` calls `indexer/pipeline/index.py` `index_repository`, which
   calls `indexer/pipeline/build.py` `build_graph`.
2. `pipeline/parse.py` `parse_source`:
   - `intake.py` `open_source` turns the argument into a folder on disk (a URL is cloned
     once, blobless) and finds its commit;
   - `discover.py` `discover` walks the folder, gives every file a language and a tier,
     and records every folder it skipped and why;
   - `parse_file` hands each file to its adapter. Deep Python and TypeScript go to their
     own adapters; other languages go to the tags adapter in `indexer/generic/`. Each
     adapter returns a `ParseResult`: nodes plus **raw** imports, calls, routes and HTTP
     calls, written as names because one file cannot see the others.
3. `build.py` `_repository_layer` runs `repo/`: packages from manifests, DEPENDS_ON
   between them, TESTS edges by naming convention, CO_CHANGES from git history.
4. Everything so far is written to the store: snapshot, files, nodes, raw calls.
5. `_run_resolvers` hands the raw items to each resolver (Python, TypeScript, structural).
   This is where names become edges, each with a **resolution** (how it was found) and a
   **confidence** (how sure).
6. `_run_linkers` runs the HTTP linker: ROUTE nodes, HANDLES and CALLS_HTTP edges.
7. `contains_edges` adds the file → class → method tree, `_external_nodes` adds a node for
   everything outside the repository that an edge points at, `_valid` drops (and counts)
   any edge whose ends do not exist, and the edges are written.
8. `mark_resolved_calls` records which raw calls got an edge. That count is the
   "resolved share" on the scoreboard.

Queries (`search`, `impact`, `ask`, the MCP tools) only read the store.

## Glossary

- **Snapshot**: one indexed commit of one repository. Everything in the store belongs to a snapshot.
- **Node**: a thing on the map: a package, module (file), class, interface, function, test, route, or external name.
- **Key**: a node's readable name, such as `backend/routes.py::create_user` or `backend/routes.py::UserService.create_user`. The **node id** is a hash of the snapshot and the key.
- **Edge**: a typed link between two nodes: CONTAINS, IMPORTS, CALLS, INHERITS, TESTS, DEPENDS_ON, CO_CHANGES, HANDLES, CALLS_HTTP.
- **Resolution**: how an edge was found, from strongest to weakest: `structural`, `direct`, `self_method`, `route_exact`, `import_scoped`, `route_pattern`, `convention`, `history`, `name_guess`.
- **Confidence**: a number from 0 to 1 that comes from the resolution. A name guess is at most 0.3, and is split between up to 5 candidates.
- **Tier**: how deeply a file is analysed. **Deep** (Python, TypeScript/JavaScript: hand-written adapters and resolvers), **structural** (any tree-sitter grammar), or **text** (a searchable file node, with the reason).
- **Adapter**: turns one file into nodes and raw items. It cannot see other files.
- **Raw items**: calls, imports, routes and HTTP calls as written (`repo.save`, `from .models import User`), before anyone knows what they point at.
- **Resolver**: turns raw items into edges, using every file in the snapshot.
- **Profile**: the small per-language part of the structural resolver: how an import maps to files, and what a file can call without importing.
- **Linker**: connects things across languages; today the HTTP linker.
- **External**: a node for something outside the repository (`::external:requests.get`), created from the edges that point at it.
- **Fixture**: `eval/fixtures/polyglot_app`, a small Python + TypeScript app whose every edge was labelled by hand. The answer key.
- **Oracle**: an outside tool used as a second answer key; here SCIP for Python (Linux only).
- **Mutant**: a copy of a repository with one function deliberately broken. The tests that fail are the truth for test selection.
- **Co-change**: files that changed in the same commits; the history signal.
- **Record and replay**: the LLM layer saves every answer by a hash of the request, and can answer only from saved answers (`replay_only`). This is what the public demo will run on.
- **MCP**: the Model Context Protocol. `codeatlas mcp` gives Claude Code the graph tools.
