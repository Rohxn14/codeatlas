# T00: Scaffold, intake, discovery and the structural tags tier

> **Reading note.** This brief is history. It is what a cloud session was told to build, kept so you can see what was asked; it is not an instruction for new work.
> - **Built in**: pull request #2, with fixes in #3 and #4.
> - **Read first**: `docs/explainers/intake-and-discovery.md`, then `docs/explainers/tags-tier.md`, for what was actually built and why.
> - **Code**: `src/codeatlas/cli.py`, `config.py`, `indexer/intake.py`, `indexer/discover.py`, `indexer/registry.py`, `indexer/generic/adapter.py`. **Tests**: `tests/test_intake.py`, `tests/test_discover.py`, `tests/test_generic_adapter.py`.
> - **Then** read this brief and its review at the end: the gap between them is where the interesting questions are.
> - Reading order, glossary and how to study a module: `docs/README.md`.

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

## Review of PR #4 (Oct 30): git mode only at the repository root

This follow-up fixes the bug you found on Windows: discovery listed files with git whenever any parent folder was a repository, so an untracked folder inside your home repository lost files.

**Verdict**: merge after fixes. **Fixes**: issue #11. Paste it into the session that built PR #4, wait for CI to go green again, then merge.

**What the PR does**: discovery uses `git ls-files` only when `git rev-parse --show-toplevel` is the scanned folder itself; any other folder (an untracked folder inside another repository, or a subfolder of a real one) is walked with the `.gitignore` files at or below it. An autouse test fixture sets `GIT_CEILING_DIRECTORIES`, and three tests are added. It merges cleanly with main's `collect_ignore` change in `tests/conftest.py`.

| Check | Result | Evidence |
| --- | --- | --- |
| Scope | PASS | 4 files: `discover.py`, the explainer, `tests/conftest.py`, `tests/test_discover.py` |
| Contract untouched | PASS | No diff in `models.py` or `indexer/adapter.py` |
| Tests | WARN | 147 passed; with pytest's temp folder inside a repository that has a commit, `test_open_folder_outside_git` still fails (must fix 1) |
| Lint | PASS | `ruff check .` clean |
| Mutation spot-check | PASS | Deleting the top-level guard (`discover.py:210-211`) fails both new tests; changing `_same_path` to `a == b` survives (should fix 3) |
| Explainer | PASS | Updated, with two wrong or stale sentences (should fix 2) |
| Safety | PASS | Only read-only git (`rev-parse`, `ls-files`) |
| Silent gaps | PASS | Every fallback walks the folder, which drops less; the CLI header says which mode ran |

**Must fix** (issue #11, part 1)
1. `tests/conftest.py:30`: git applies a ceiling only to folders strictly above it, so a ceiling at `tmp_path` does not stop `git -C tmp_path` from finding a parent repository. Set it to `tmp_path.parent`. Your home repository had no commits, which is why only one test failed on your machine; with a commit, more would. (You have since renamed it to `.git-disabled`, so your machine is safe either way.)

**Should fix** (issue #11, parts 2 to 4)
1. `intake.py:104`: a walked folder still records the outer repository's HEAD as its commit, so its snapshot id would be wrong. Record a SHA only at a repository's top level, using one shared helper.
2. Docstrings and the explainer say the old bug lost files the outer repository "does not track"; it lost only files the outer repository *ignores* (`--others` lists untracked files).
3. `_same_path` (`discover.py:227-229`), where Windows paths could go wrong, has no test.
4. `tests/test_discover.py:132`: the file named `untracked_but_new.py` is actually committed.

**Your decisions** (write your answer next to each)

| # | Question | Recommendation |
| --- | --- | --- |
| 1 | Walk a subfolder of a repository too, instead of using git? | Accept: it never loses files. Watch for build folders (`target/`, `out/`) using up `max_files` |
| 2 | Should the snapshot SHA follow the same top-level rule? | Yes (should fix 1) |
| 3 | Keep the ceiling fixture autouse? | Yes, with the ceiling at `tmp_path.parent` |

**Try it yourself** (PowerShell, after `gh pr checkout 4`)

```powershell
$d="$env:TEMP\ca-demo"; mkdir "$d\outer\project" -Force | Out-Null; git -C "$d\outer" init -q
Set-Content "$d\outer\.gitignore" "*"; Set-Content "$d\outer\project\app.py" "def main(): pass"
codeatlas scan "$d\outer\project"
```

Expected: the header says `(files listed by walk)` and the census has a row `python ... 1`. On the old main it said `listed by git` and the census was empty: the bug you hit.

**Read these yourself**
- `src/codeatlas/indexer/discover.py:202-239`: the top-level rule and `_same_path`, the part most likely to behave differently on Windows.
- `src/codeatlas/cli.py:89-94` with `src/codeatlas/indexer/intake.py:101-104`: how the snapshot id is chosen, and why should fix 1 matters once the store keys everything by it.
