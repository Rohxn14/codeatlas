# CodeAtlas

CodeAtlas takes a repository, in any mix of languages, and builds an **honest map** of it:
packages, files, symbols, calls, tests and change history. Every fact on the map says
how it was found (a resolved import, a naming convention, a name guess, git history) and
how sure it is (a confidence from 0 to 1). On top of the map sit hybrid search, an
**impact engine** that predicts what a change will break and which tests to run, an agent
that answers questions with checked citations, and an MCP server that gives Claude Code
the same tools.

CodeAtlas analyses code statically. It never installs, imports or runs code from the
repository it indexes. No file is dropped quietly: a file it cannot analyse still gets a
node with its language, its tier and the reason.

**Status (Nov 2026):** v1 works end to end and is measured on 47 public repositories.
Next: an impact engine v2 and a free public demo that replays recorded agent runs instead
of calling a live model.

## Install

```
python -m pip install -e ".[dev]"
```

Python 3.11 or newer, on Windows (PowerShell) or Linux. `ask` and the Ask tab need `GROQ_API_KEY`
or `GEMINI_API_KEY`: copy `.env.example` to `.env` (ignored by git) and fill it in.
Everything else works offline.

## A five-command tour

On the fixture in this repository, a small Flask-style backend with a TypeScript frontend
(output from a real run, trimmed where marked).

**1. Index** a folder or `https://github.com/owner/repo[@ref]` (a blobless clone with full history):

```
$ codeatlas index eval/fixtures/polyglot_app
CodeAtlas 0.1.0: polyglot_app@2bae7bcbe8b2
...
total: 28 files (deep: 21, text: 7); skipped: 0

Nodes: class 7, external 22, function 33, interface 2, module 28, package 2, route 3, test 11
Edges: 226
  by kind: calls 66, calls_http 6, contains 81, handles 3, imports 48, inherits 3, tests 19
  by resolution: convention 4, direct 56, import_scoped 11, route_exact 4, route_pattern 2, self_method 14, structural 135
Raw calls: 124, resolved 72, unresolved 52 (python 22, tsx 5, typescript 25)
```

**2. View** the map as one self-contained HTML page (census, packages, a file and symbol
explorer, a neighbourhood graph, and every problem found):

```
$ codeatlas view
wrote .codeatlas/view.html (108 nodes, 226 edges)
```

`codeatlas view --impact change.diff` adds a section listing what the diff changes and
could break, and colours those nodes in the graph.

`codeatlas serve` opens the local web app instead (being built, see
`docs/plans/app-v1.md`). So far: a map, file and symbol pages, search and coverage. **Map** is an
architecture diagram drawn from the stored edges: folders and files as boxes, an arrow
where code in one uses code in another, and a click on an arrow lists the edges behind
it. A **file** page shows its source, its symbols and the files around it; a
**symbol** page shows what uses it and what it uses, each with how it was found.
**Coverage** shows how deeply each language was read, how sure the edges are, and
what could not be analysed.

**3. Search** (BM25 plus embeddings fused by rank, then one hop along the graph):

```
$ codeatlas search "create user" -k 5
  1  0.0164  function  backend/routes.py::create_user  backend/routes.py:30  [bm25]
  2  0.0161  function  backend/services.py::UserService.create_user  backend/services.py:16  [bm25]
  3  0.0159  test      backend/tests/test_services.py::TestUserService.test_create_user_assigns_ids  backend/tests/test_services.py:14  [bm25]
  4  0.0156  function  backend/app.py::create_app  backend/app.py:6  [bm25]
  5  0.0154  function  backend/handlers.py::handle_create  backend/handlers.py:9  [bm25]
note: no embeddings for this snapshot: BM25 only
```

`--embed` builds the embeddings first (a local model, downloaded once).

**4. Impact**: what a change could break, each target with the evidence behind it. The
change comes from `--diff FILE`, `--diff -` (stdin), `--git REV` (runs `git diff REV` in
the indexed checkout) or `--files a.py b.ts`:

```
$ codeatlas impact --files backend/user_repo.py --top 4
snapshot polyglot_app@2bae7bcbe8b2: 1 changed files, 4 changed symbols
changed: backend/user_repo.py::, backend/user_repo.py::UserRepo, backend/user_repo.py::UserRepo.save, backend/user_repo.py::UserRepo.find_by_name

10 targets, top 4 shown
  1  0.800  module    backend/routes.py::
       graph 0.800: backend/user_repo.py::UserRepo <-imports 1- backend/routes.py::
  2  0.800  module    backend/services.py::
       graph 0.800: backend/user_repo.py::UserRepo <-imports 1- backend/services.py::
  3  0.800  module    backend/tests/test_services.py::
       graph 0.800: backend/user_repo.py::UserRepo <-imports 1- backend/tests/test_services.py::
  4  0.800  test      backend/tests/test_services.py::test_find_by_name
       graph 0.800: backend/user_repo.py::UserRepo.find_by_name <-calls 1- backend/tests/test_services.py::test_find_by_name
```

`codeatlas tests` takes the same inputs and ranks the tests to run:

```
$ codeatlas tests --files backend/user_repo.py --top 3
...
  3  0.576  module    backend/tests/test_routes.py::
       tests 0.576: backend/user_repo.py::UserRepo <-imports 1- backend/routes.py:: <-tests 0.8- backend/tests/test_routes.py:: (convention)

test files to run (score >= 0.3): 2 of 4; skipped share 50%
  backend/tests/test_services.py
  backend/tests/test_routes.py
```

**5. Ask** the agent. It calls the same graph tools as the MCP server, cites
`repo@sha:path:line`, and every citation is checked against the snapshot:

```
$ codeatlas ask "Which tests cover UserRepo.save?"
```

It prints the answer, each citation marked `ok` or `INVALID` (with the reason), steps and
tokens, and the path of the trajectory file. Without a key it exits with code 2:

```
$ codeatlas ask "x"
codeatlas: ask needs a language model: set GROQ_API_KEY or GEMINI_API_KEY in .env or in the environment
```

(The run for this README hit provider rate limits, so no answer is pasted here.)

Every query command takes `--db`, `--snapshot` (default: the latest) and `--json`.
`codeatlas scan` prints a census without writing a database; `codeatlas export` writes the
graph as JSON. A longer run on a real repository is in [docs/demo.md](docs/demo.md).

## Tiers and languages

| Tier | Languages | What you get |
| --- | --- | --- |
| deep | Python, TypeScript, JavaScript (and TSX) | hand-written adapters and resolvers: imports, types of receivers, routes, HTTP client calls, tests |
| structural, with a resolution profile | Java, Go, C#, PHP, Ruby, C, C++, Rust | tree-sitter definitions and calls, imports resolved by one import-scoped resolver |
| structural, name guesses | Scala, Lua, Swift, Elixir (the other bundled grammars) | definitions and calls; a call is matched by name, at low confidence, at most 5 candidates |
| text | everything else | one searchable node per file, with the reason |

The repository layer works for every language: manifests, packages and their
dependencies, test files by convention, and co-change from git history. The HTTP linker
joins client calls to server routes across languages.

## How well it works

The acceptance suite indexes 47 pinned public repositories. The newest run
(`eval/results/suite_20261126.md`, Nov 26, on a Windows laptop; what changed since the run
before is in `eval/results/README.md`): 46 run, all completed, and linux not run (its clone
is several GB). 45 indexed to the end: 29,808 files (deep 4,957, structural 9,005, text
15,846) in 37 languages, 882,204 raw calls of which 48.7% stay unresolved, 316 seconds for
all of them. microsoft/TypeScript (68,192 files) does not fit the suite's 300 seconds a
repository; alone, within the one-hour limit, it indexes in 970 seconds.

"Resolved" means a call got an edge, not that the edge is right. On click, a sample of 90
CALLS edges checked against the code (`eval/results/precision_click_20261127.md`): every
edge found from what the code says was right (50 of 50), name guesses were right 25% of
the time at a confidence of about 0.2, import-scoped guesses 30% at about 0.45; about 76%
of all of click's CALLS edges are right. One repository, labelled by a model with a
reason per row.

On `polyglot_app` the graph scores 165 of 165 labelled edges at precision 1.0. Test
selection reaches F1 0.84 on both mutation benchmarks (run-everything scores 0.52 and
0.72) while skipping 46-64% of test files. Predicting which files change together, the
engine does not yet beat plain co-change history.

## MCP for Claude Code

```
codeatlas index path/to/repo --db /absolute/path/atlas.db
claude mcp add codeatlas -- codeatlas mcp --db /absolute/path/atlas.db
claude mcp list
```

Claude Code then has `search_symbols`, `find_callers`, `find_callees`, `impact`,
`select_tests` and the other graph tools. `python -m codeatlas.agent mcp` does the same.

## Limits

- Set in `codeatlas.toml`: 200,000 files and 3,600 seconds per index. When one is
  reached, CodeAtlas keeps what it has and names the limit under `limits hit`. A text file
  over 5 MB is not parsed into symbols; its text is still searchable.
- Resolution is static. Dynamic dispatch, reflection, `getattr`, dependency injection and
  monkeypatching are missed or guessed; a guess is labelled `name_guess` with a low
  confidence.
- Outside the deep tier, receivers have no types, so method calls on objects are name
  guesses unless the language profile can scope them by import.
- The impact engine reads the graph and history; it cannot see behaviour changes that
  flow through data, configuration or files it could not parse.
- `--git REV` needs the indexed checkout on disk and compares `REV` with the working tree.
  If the checkout has moved past the indexed commit it exits 2 and asks for
  `codeatlas index --force`. A URL is cloned blobless with full history, so `--git` may
  fetch old file contents over the network.
- `ask` depends on a free-tier LLM and can fail on rate limits; the trajectory is kept.

## Project layout

```
src/codeatlas/
  cli.py                 the codeatlas command
  models.py              the shared types (see docs/contract.md)
  indexer/
    intake.py discover.py registry.py   a folder or URL becomes files with languages and tiers
    generic/             the tags adapter: any tree-sitter language
    languages/python/    deep adapter, and resolver/
    languages/typescript/ deep adapter, and resolver/
    structural/          one import-scoped resolver plus a profile per language
    queries/             tree-sitter queries (tags extras, imports)
    linker/              HTTP client calls to server routes
    pipeline/            one build, start to end; the index report
  repo/                  manifests, packages, test conventions, co-change
  store/                 SQLite, FTS5, the NetworkX view
  search/                hybrid search
  llm/                   Groq and Gemini, record and replay, embeddings
  agent/                 the agent loop, its tools, the MCP server
  impact/                diffs to changed symbols, impact ranking, test selection
  view/                  the HTML viewer
  web/                   the local web app behind `codeatlas serve`
eval/                    fixture, oracle, acceptance suite, mutants, co-change benchmark
docs/                    start at docs/README.md
```

## Develop

On Windows (PowerShell):

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
ruff check .
pytest -q                          # about 1,170 tests, about two minutes; no network
python scripts/score_fixture.py    # the fixture graph against its hand-made labels
python -m eval.suite --only click  # one repository of the acceptance suite
```

CI runs lint and tests on Linux and Windows, Python 3.11 and 3.12, for every push and
pull request. Work goes through a branch and a pull request.

## Learn how it works

[docs/README.md](docs/README.md) is the way in: what each document is for, the order to
read the modules in (following one repository through the system), how to study a
module, a glossary, and one build traced through the code.

Each module has an explainer in [docs/explainers/](docs/explainers/) (What, Why, How with
a worked example, Where). The shared types are in [docs/contract.md](docs/contract.md).
