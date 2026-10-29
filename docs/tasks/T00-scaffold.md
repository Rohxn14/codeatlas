# T00: Scaffold, intake, discovery and the structural tags tier

**Wave**: Day 0 (one session, merged before Wave 1)
**Branch**: `task/T00-scaffold`

## Goal

Create the package skeleton every later task builds on, plus the first working slice: take a local path or a public GitHub URL, discover every file, detect its language and tier, and extract definitions and name-level calls for any language through tree-sitter tags queries. Finish with `codeatlas scan <path-or-url>` printing a per-language summary.

## Context

- `src/codeatlas/models.py` and `src/codeatlas/indexer/adapter.py` already exist; the owner typed them from `docs/contract.md`. Do not edit them. If they do not match the contract, stop and report it.
- This task declares **every** dependency the project will need, so later parallel sessions never touch `pyproject.toml`.

## Files you may create or edit

- `pyproject.toml`, `README.md`, `.gitignore`, `.github/workflows/ci.yml`
- `.claude/settings.json`, `scripts/install_pkgs.py` (or `.sh`; see step 7)
- `src/codeatlas/__init__.py`, `src/codeatlas/cli.py`
- `src/codeatlas/indexer/__init__.py`, `intake.py`, `discover.py`, `registry.py`, `generic/`, `queries/`
- `src/codeatlas/config.py` and an example `codeatlas.toml`
- Empty packages with an `__init__.py` and a one-line docstring: `repo/`, `store/`, `search/`, `impact/`, `agent/`, `memory/`, `llm/`, `indexer/structural/`, `indexer/languages/python/`, `indexer/languages/typescript/`
- `eval/` folders with a `README.md` each: `fixtures/`, `oracle/`, `qa/`, `mutants/`, `results/`
- `tests/` for everything above, including `tests/test_contract.py`
- `docs/explainers/intake-and-discovery.md`, `docs/explainers/tags-tier.md`

## Steps

1. **`pyproject.toml`**: package `codeatlas`, `src/` layout, Python `>=3.11`, console script `codeatlas = codeatlas.cli:main`. Declare these dependency groups:
   - runtime: `tree-sitter`, grammar packages covering at least Python, TypeScript, TSX, JavaScript, Go, Java, Rust, C#, PHP (choose either individual `tree-sitter-*` packages or one maintained language pack; explain the choice), `networkx`, `numpy`, `pathspec`, `pyyaml`, `fastembed`, `groq`, `google-genai`, `httpx`, `mcp` (the Model Context Protocol SDK, for a possible Wave 3 server)
   - dev: `pytest`, `ruff`
   Pin lower bounds only.
2. **Contract test** `tests/test_contract.py`: import both contract files and assert every enum member, data-class field name and default, protocol method and the three id helpers listed in `docs/contract.md` exist. This catches typos in the owner's files.
3. **Intake and limits** `indexer/intake.py` and `config.py`: accept a local path or a public GitHub URL (`https://github.com/owner/repo`, with an optional `@ref`). For a URL, check the host is `github.com`, then run `git clone --filter=blob:none --single-branch` (adding `--branch <ref>` when given) into `.codeatlas/repos/<owner>__<repo>/`, record the commit SHA, and reuse the clone when the SHA is unchanged. The blobless clone keeps the full commit history, which the repository layer's co-change analysis needs, while downloading file contents only for the checked-out commit. Add a config value `max_history_commits` (default 2,000) for later tasks. Never call the GitHub REST API per file, and never run anything from the cloned repository. Read limits from `codeatlas.toml` with defaults of 20,000 source files, 1 MB per file and 300 seconds per index; when one is reached, stop, keep what was indexed, and name the limit in `Snapshot.limits_hit`. Tests must not use the network: test URL parsing on its own, and the clone path against a temporary local git repository.
4. **Discovery** `indexer/discover.py`: list files with `git ls-files` when the path is a git repo, otherwise walk the tree honouring `.gitignore` via `pathspec`. Always skip `node_modules`, `.venv`, `venv`, `dist`, `build`, `.git`, minified files (`*.min.js`), binaries (NUL byte in the first 8 KB) and files over 1 MB. Map extensions to grammar names (`.ts` → `typescript`, `.tsx` → `tsx`, `.js/.mjs/.cjs/.jsx` → `javascript`, and so on). Files with no grammar become tier `TEXT`. Return `list[FileRecord]` with SHA-256 hashes and forward-slash paths.
5. **Tags queries** `indexer/queries/<language>/tags.scm`: use the queries shipped with the grammar packages if they include them; otherwise vendor each grammar's `queries/tags.scm` from its upstream repository, with a `LICENSE-NOTICE.md` naming the source and licence.
6. **Generic adapter** `indexer/generic/`: one class implementing `LanguageAdapter`, constructed per language with its grammar and tags query. Captures `@definition.*` become nodes (`function`, `method` → FUNCTION with `owner_key` when nested in a class; `class` → CLASS; `interface` → INTERFACE; `module` captures are ignored because the file is the module). Captures `@reference.call` become `RawCall` with `caller_key` set to the innermost enclosing definition. Always emit the MODULE node first. Never raise on syntax errors: record them in `errors`.
7. **Registry** `indexer/registry.py`: maps a grammar name to an adapter; deep adapters (added in T01 and T02) register for their languages and take precedence over the tags adapter, which reports tier `STRUCTURAL`; languages with no grammar get a TEXT-tier adapter that emits only the module node.
8. **Cloud install hook**: `.claude/settings.json` with a `SessionStart` hook (matcher `startup|resume`) that runs an install script. The script exits immediately unless `CLAUDE_CODE_REMOTE` is `true`, then installs the project with dev extras, skipping the install when `pyproject.toml` has not changed since the last success (store a hash). It must exit 0.
9. **CLI** `codeatlas scan <path-or-url> [--json]`: run intake, discovery and every adapter, print a language census (every language found, with file counts and bytes, sorted by size) and then a table per language: tier, nodes by kind, raw calls, parse errors, plus any limits hit. Every discovered file must appear in exactly one row, so the totals prove nothing was skipped. `--json` prints the same data as JSON.
10. **CI** `.github/workflows/ci.yml`: on push and pull request, matrix `ubuntu-latest` and `windows-latest`, Python 3.11 and 3.12; install with dev extras; run `ruff check .` and `pytest -q`.

## Tests (all must pass)

- Contract test from step 2.
- Intake: URL parsing (valid, `@ref`, non-GitHub host rejected); clone and SHA reuse against a temporary local repository; the file limit stops discovery and records `max_files`.
- Discovery on a temporary directory: ignores `node_modules` and `.gitignore`d files, detects languages, marks text files, produces forward-slash paths.
- Generic adapter on small snippets for Go, Java and Rust (put them in `tests/data/generic/`): correct definitions, owner keys for methods, call captures with the right caller key, module node first.
- A deliberately broken file yields a result with `errors` filled and no exception.
- `codeatlas scan tests/data/generic --json` exits 0 and reports each language.

## Out of scope

Deep Python or TypeScript extraction, the store, resolution of any kind, LLM code.

## Done when

`codeatlas scan` works on this repository itself and on the generic test data; in the pull request, report whether `codeatlas scan https://github.com/pallets/click` worked from the cloud session (a failure there is information, not a blocker); CI is green on Linux and Windows; both explainers are written.
