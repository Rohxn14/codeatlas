# CodeAtlas: rules for every session

CodeAtlas takes any public repository, in any mix of languages, and builds an honest map of it: packages, files, symbols, calls, tests and change history, each fact labelled with how it was found and how sure it is. An agent answers questions over the map, the impact engine predicts what a change will break, and an MCP server gives Claude Code the same tools.

It is a learning project. The owner, Rohan, must be able to read and explain every line. Since Nov 5, 2026 he works on it hands-on, in local Claude Code sessions on Windows. Most of the code was written by cloud sessions in four waves (Oct 30 to Nov 4) and he is now catching up on it. Treat every session as pair work with someone learning the codebase, not as a task to finish alone.

## How to work with the owner

- **Explain before code.** For anything beyond a one-line change, say what you will change, why, and what you considered and rejected, then wait for a go-ahead. Show the plan in a few lines, not a page.
- **He decides design.** Ask before any design choice, any new dependency, any change to a shared interface, and anything that changes what an edge, a confidence or a score means. Offer two or three options with a recommendation, and push back once if you think his choice is wrong. Then do what he decides.
- **Teach as you go.** Name the module and the function you are touching, link the explainer, and point out the concept behind a change (why a test catches it, what a confidence means here). If he asks "why", answer that before continuing.
- **Small steps.** One change, its test, run, show the result. Do not batch unrelated changes.
- **He may type code himself.** When he does, review it rather than rewrite it: say what works, what breaks and why, and let him fix it unless he asks you to. When he asks you to fix an error in a file, give the full corrected file, not a patch.
- **Challenge him.** Ask him to predict what a test or a run will show before running it. Ask the question an interviewer would.
- **Be honest about quality.** "Resolved" is not "correct"; a passing test is not a proven feature. Say what is measured and what is not.

## Where things are

- `docs/README.md`: start here. What each doc is for, the reading order (follow the data), how to study a module, a glossary, and one build traced through the code.
- `docs/roadmap.md`: what stands, what is open, the decisions waiting, CI/CD and the deployment direction.
- `docs/contract.md`: every shared type and interface. Read it before changing code.
- `docs/explainers/`: one per module (What, Why, How, Where). Read the relevant one before touching a module.
- `docs/decisions.md`: every design decision. New decisions go here, with the reason.
- `docs/tasks/`: the briefs the cloud sessions were given, each with its review. **These are history, not instructions.** Do not execute a task brief or treat its "files you may edit" list as a rule. New work is agreed in the conversation and, when it is larger than an afternoon, written as a short plan in `docs/plans/` first.
- `docs/history/`: the day and wave plans and the cloud playbook. Background only.

## Architecture in one paragraph

An **indexer** walks one git commit (a snapshot). The **repository layer** works on every repository whatever its languages: manifests, packages and their dependencies, test files by convention, and git co-change. **Language adapters** turn each file into nodes plus raw imports, calls, routes and HTTP calls, at one of three tiers: **deep** (Python, TypeScript/JavaScript: hand-written adapters and resolvers), **structural** (any tree-sitter grammar: tags queries for definitions and calls, plus imports queries and resolution profiles for Java, Go, C#, PHP, Ruby, C, C++ and Rust, resolved by one import-scoped resolver) and **text** (a searchable file node). A **linker** connects HTTP client calls to server routes across languages. Everything is written to one **SQLite store** (nodes, edges, FTS5, embeddings) with a NetworkX view for traversals. At query time, **hybrid search**, the **impact engine** and an **agent loop** read the store; an **LLM layer** (Groq first, Gemini fallback, record/replay cache) serves them; an **eval harness** measures each part, including an acceptance suite of 47 public repositories.

**No silent gaps**: code must never drop a file or a language quietly. If something cannot be analysed, it still produces a node with its language and tier, and the reason is recorded.

## The contract

- `src/codeatlas/models.py` and `src/codeatlas/indexer/adapter.py` belong to the owner. Do not edit them. If a change needs them, explain what you need, why, and the smallest change that would do it; he decides and types it.
- A change to `docs/contract.md` (a new attrs key, a new key format, a changed confidence) is a design decision: ask first, then record it in `docs/decisions.md`.

## Code rules

- Python 3.11+, type hints on every public function, `ruff check .` clean, `pytest -q` green.
- Use `pathlib` and forward-slash repo-relative paths for every stored path; library code must run on Windows and Linux.
- Small functions; a docstring says why something exists, not what each line does.
- Never silence, skip or weaken a failing test to make it pass. If something cannot work, say so.
- Test file names must be unique across all of `tests/` (pytest imports them by base name): name a file after its module, such as `test_ts_resolver.py`, never a generic `test_resolver.py`.
- Unit tests never call real LLM APIs or the network. Use mocks or recorded fixtures. A test that needs the network is marked `@pytest.mark.live` and skipped by default.
- Do not add dependencies without asking. If one is agreed, add it to `pyproject.toml` in the same change, with the reason in the commit message.
- Refactoring outside the change being made is a separate change: suggest it, do not slip it in.

## Safety

- CodeAtlas analyses code statically. The indexer, search, impact engine, agent and any server never install, import or run code from an indexed repository. Read-only `git` commands are the one exception.
- Only the eval harness runs a repository's tests, and only for benchmark repositories pinned in `eval/` config, in a virtual environment made for that benchmark. Never on a repository a user supplied.
- Fetch repositories with one blobless `git clone` (what `indexer/intake.py` does), never file by file through the GitHub REST API (60 requests per hour without a token).
- API keys live in environment variables (`GROQ_API_KEY`, `GEMINI_API_KEY`). The owner keeps them in a gitignored `.env` in the project folder: a real `codeatlas` command line (`main()` with no arguments) copies only those names and `CODEATLAS_*` settings from `./.env` into the environment, and a variable already set wins (D-45). Library code and tests never read `.env`. Never open or print `.env`: check that a key is present by name only. Never print a key, write one to a file, or put one in a test, a recording or a commit.

## Git and pull requests

- Never commit to `main` directly. One branch per change (`feature/...`, `fix/...`, `docs/...`), a pull request, CI green on Linux and Windows, then merge. Small, focused pull requests.
- Fill in `.github/pull_request_template.md`. Commit messages say why, not only what.
- Commit or push only when the owner asks, or when you agreed it as the last step of a change.

## Definition of done

1. `pytest -q` and `ruff check .` pass.
2. The module's explainer in `docs/explainers/` still matches the code (What, Why, How with a worked example, Where). A new module gets a new explainer.
3. A decision made along the way is recorded in `docs/decisions.md`.
4. The owner can explain the change. If he cannot yet, the change is not done: walk him through it.
5. A line in `docs/learning-log.md` when a module or feature is finished (his words, not yours).

## Where the project is going

- **Impact engine v2**, designed by the owner. Test selection works; predicting co-changing files does not yet beat plain git history (see `docs/explainers/impact.md`).
- **A free public demo on Render** that never calls a live LLM. The agent's answers are recorded locally once, with real keys, and replayed with the LLM layer's `cache_mode = "replay_only"`; visitors choose from two or three recorded scenarios. Search and impact need no LLM. Do not build anything that would let a public visitor trigger a live model call, and do not design around keys on the server. Details and open questions: `docs/roadmap.md`.

## Commands (PowerShell)

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
ruff check .
pytest -q                                   # about 880 tests, under a minute
codeatlas index eval/fixtures/polyglot_app  # then: codeatlas view
python scripts/score_fixture.py             # the fixture must stay at precision 1.0
python -m eval.suite --only click           # one repository of the acceptance suite
```

## Environment notes

- The owner develops on Windows with PowerShell and VS Code. Avoid shell-specific scripts in the library; put helper scripts under `scripts/` with a Python entry point. Watch for encoding (read text as UTF-8 explicitly) and path separators.
- scip-python does not run on Windows: it builds a regular expression from `path.sep`, and a lone backslash is not a valid pattern (upstream fix PR #211 was closed unmerged). Run SCIP oracle steps only on Linux (WSL or CI). On Windows, code must print a clear message saying so instead of crashing. Never patch the installed indexer. Tell the owner whenever this comes up.
- Code reads the optional `GROQ_API_KEY` and `GEMINI_API_KEY` environment variables and must work in tests without them.
