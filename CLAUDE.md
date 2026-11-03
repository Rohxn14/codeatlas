# CodeAtlas: rules for every session

CodeAtlas takes any public repository, in any mix of languages, and builds an honest map of it: packages, files, symbols, calls, tests and change history, each fact labelled with how it was found and how sure it is. An agent answers questions over the map, the impact engine predicts what a change will break, and an MCP server gives Claude Code the same tools. It is a learning project: the owner reads and must be able to explain every line you write.

## Architecture in one paragraph

An **indexer** walks one git commit (a snapshot). The **repository layer** works on every repository whatever its languages: manifests, packages and their dependencies, test files by convention, and git co-change. **Language adapters** turn each file into nodes plus raw imports, calls, routes and HTTP calls, at one of three tiers: **deep** (Python, TypeScript/JavaScript: hand-written adapters and resolvers), **structural** (any tree-sitter grammar: tags queries for definitions and calls, plus imports queries and resolution profiles for about a dozen languages, resolved by one import-scoped resolver) and **text** (a searchable file node). A **linker** connects HTTP client calls to server routes across languages. Everything is written to one **SQLite store** (nodes, edges, FTS5, embeddings) with a NetworkX view for traversals. At query time, **hybrid search**, the **impact engine** and an **agent loop** read the store; an **LLM layer** (Groq first, Gemini fallback, record/replay cache) serves them; an **eval harness** measures each part, including an acceptance suite of about 40 public repositories.

**No silent gaps**: code you write must never drop a file or a language quietly. If something cannot be analysed, it still produces a node with its language and tier, and the reason is recorded.

## The contract

- `docs/contract.md` defines every shared type and interface. Read it before writing code.
- **Never edit** `src/codeatlas/models.py` or `src/codeatlas/indexer/adapter.py`. The owner types and maintains them.
- If your task cannot be done without a contract change, stop, and write a section titled `Contract change request` in your pull request: what you need, why, and the smallest change that would do it.

## Scope rules

- Your task brief (`docs/tasks/Txx-*.md`) lists the files and folders you may create or edit. Stay inside them, plus tests for them and your explainer.
- Do not add dependencies. T00 declares them all in `pyproject.toml`. If one is truly unavoidable, explain why in the pull request and do not edit `pyproject.toml` yourself.
- Do not refactor code outside your folder, even if you see a problem; note it in the pull request instead.

## Code rules

- Python 3.11+, type hints on every public function, `ruff check` clean, `pytest -q` green.
- Use `pathlib` and forward-slash repo-relative paths for every stored path; library code must run on Windows and Linux.
- Small functions; a docstring says why something exists, not what each line does.
- Never silence or skip a failing test to finish. If something cannot work, say so in the pull request.
- Test file names must be unique across all of `tests/` (pytest imports them by base name): name yours after your module, such as `test_ts_resolver.py`, never a generic `test_resolver.py`. Two parallel pull requests can each pass CI and still break main together.
- Unit tests never call real LLM APIs or the network. Use mocks or recorded fixtures. A test that needs the network is marked `@pytest.mark.live` and skipped by default.

## Cost discipline

Sessions run on a small, fixed credit, so spend it on code, not on loops.

- If an external service fails (an API call, a clone, a download, a tool install), try at most twice, then record the exact error in the pull request, continue with mocks or fixtures, and move on.
- Do not stop to ask the owner about choices the brief leaves open: pick the simplest reasonable option and list it under "Questions for the owner". Stop only for a contract change, or where your brief asks you to stop after a plan for review. Sessions often run overnight, and a question left waiting wastes the night.
- Run targeted tests while developing and the full suite once at the end; do not re-read large files you have already read.
- Do not install tools beyond what `pyproject.toml` and the environment's setup script provide.

## Safety

- CodeAtlas analyses code statically. The indexer, search, impact engine, agent and any server never install, import or run code from an indexed repository.
- Only the eval harness runs a repository's tests, and only for benchmark repositories pinned in `eval/` config, inside the cloud VM or a container.
- Fetch repositories with a shallow `git clone`, never file by file through the GitHub REST API (its unauthenticated limit is 60 requests per hour).

## Definition of done

1. Tests pass: `pytest -q`; lint passes: `ruff check .`
2. An explainer at `docs/explainers/<module>.md` with four headed parts:
   - **What**: what the module does, in plain words
   - **Why**: the design choices and the alternatives you rejected
   - **How**: the algorithm, step by step, with a small worked example
   - **Where**: how it connects to other modules and which contract types it uses
3. One pull request titled `Txx: <short summary>` that fills in every section of `.github/pull_request_template.md`. Keep the branch name the cloud environment gives you (`claude/...`); the title is how the owner finds the task. Under "Questions for the owner", list the design choices you made that the brief left open, so the owner can confirm or reverse them.

## Environment notes

- Cloud sessions run on Linux; the owner develops on Windows with PowerShell. Avoid shell-specific scripts in the library; put helper scripts under `scripts/` with a Python entry point.
- scip-python does not run on Windows: it builds a regular expression from `path.sep`, and a lone backslash is not a valid pattern (upstream fix PR #211 was closed unmerged). Run SCIP oracle steps only on Linux (a cloud session or WSL). On Windows, code must print a clear message saying so instead of crashing. Never patch the installed indexer.
- LLM keys are attached by the environment's network proxy; code reads optional `GROQ_API_KEY` and `GEMINI_API_KEY` environment variables but must work in tests without them.
