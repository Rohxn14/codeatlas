# T19: Command line for search, ask, impact and tests; README

> **Reading note.** This brief is history. It is what a cloud session was told to build, kept so you can see what was asked; it is not an instruction for new work.
> - **Built in**: pull request #36, with fixes in #38.
> - **Read first**: `docs/explainers/cli.md`, for what was actually built and why.
> - **Code**: `src/codeatlas/cli.py`. **Tests**: `tests/test_cli_commands.py`.
> - **Then** read this brief and its review at the end: the gap between them is where the interesting questions are.
> - Reading order, glossary and how to study a module: `docs/README.md`.

**Wave**: 4 (runs in parallel with T20 and T21; no file overlap)
**Branch**: keep the one the cloud environment gives you

## Goal

Everything CodeAtlas can do should be one `codeatlas` command away. Today `cli.py` has `scan`, `index`, `view` and `export`; search lives in `python -m codeatlas.search`, the agent and MCP server in `python -m codeatlas.agent`, and the impact engine (T12) has no command at all. This task adds the commands and rewrites the README, which still describes the Day 0 scaffold.

## Plan first, then build

Write `docs/plans/T19.md` (half a page) as your first commit, then keep going: each command's arguments and output, and how `impact` gets its diff.

## Files you may create or edit

- `src/codeatlas/cli.py`
- `src/codeatlas/view/` (only for the `--impact` option below)
- `README.md`, `docs/explainers/cli.md`, `docs/plans/T19.md`, `docs/demo.md`
- `tests/test_cli_commands.py` (or other new test files with unique names)

Call into the existing modules; do not change `search/`, `agent/`, `impact/`, the store or the pipeline. Keep `python -m codeatlas.search` and `python -m codeatlas.agent` working.

## Commands

All take `--db` and `--snapshot` like `view` (default: the latest snapshot), and `--json` for machine output.

- `codeatlas search "query" [-k 10] [--no-expand] [--embed]`: hybrid search (`search/hybrid.py`); print rank, score, kind, key, path:line.
- `codeatlas ask "question" [--max-steps 20]`: the agent loop (`agent/loop.py` `ask`); print the answer, its citations marked valid or invalid, and the trajectory path. With no LLM key, exit 2 with a one-line message naming `GROQ_API_KEY`/`GEMINI_API_KEY`.
- `codeatlas impact [--diff FILE | --diff - | --git REV | --files a.py b.ts]`: `impact/diff.py` `parse_diff` plus `impact/engine.py` `impact`. `--git REV` runs `git diff REV` in the snapshot's checkout (read the root from the snapshot record; this runs git, never the repository's code). Print ranked targets with score and one evidence line each, then the warnings. Options: `--depth`, `--decay`, `--top 20`.
- `codeatlas tests ...`: the same inputs; print the ranked tests with evidence, and the share of test files skipped.
- `codeatlas mcp`: serve the MCP tools on stdio (as `python -m codeatlas.agent mcp`).
- `codeatlas view --impact FILE`: optional, if time allows. Highlight the changed nodes and the top targets in the page.

## README

Rewrite `README.md` for a reader who has never seen the project. Cover what it is (the honest map: each fact with how it was found and how sure it is), install, a five-command tour on `eval/fixtures/polyglot_app` (index, view, search, impact, ask) with real output pasted from your run, the tiers and languages table as they are now (deep: Python, TypeScript/JavaScript; profiles: Java, Go, C#, PHP, Ruby, C, C++, Rust; name guesses: the rest), the latest acceptance-suite numbers (`eval/results/`, newest file), the MCP setup for Claude Code (the `claude mcp add` line), and the limits. Keep it under 200 lines; link to `docs/explainers/` for depth.

`docs/demo.md`: one end-to-end run on a real public repository (pick a small one from `eval/suite/repos.yaml`; shallow clone, at most two attempts): `index`, a `search`, an `impact` on a real recent commit (`--git HEAD~1`) with its ranked tests, and an `ask` if an LLM key is available in the session (otherwise say so). Paste real output, trimmed.

## Tests

The CLI on a small repository built in the test: each command's exit code and the key lines of output, `--json` parseable, `impact` from `--diff -` (stdin), `--files` and `--git` (a temporary git repository with two commits), and `ask` with no key exits 2. The LLM is mocked; no network.

## Done when

The commands work on the fixture; tests pass on Linux and Windows CI; `ruff check .` passes; README and demo contain real output; explainer has What/Why/How/Where. Pull request title: `T19: CLI commands and README`.

## Review (Nov 4)

**Verdict**: merged (#36); meets "Done when". Every command exists with its options, error paths exit 2 with one line instead of a traceback, and the README's pasted output matches a re-run. Fixed in #38 (the fixes were pushed after #36 had been merged, so they came in a follow-up pull request): `--git` now refuses a checkout that has moved past the indexed commit; text that is not a diff exits 2 instead of reporting zero targets; stdin is read as UTF-8, which matters on Windows; the docs describe the blobless clone correctly; `search` and `ask` pass `--config` to the LLM clients. Left open: `--git` cannot find the checkout when the source was a relative path and you run from another folder (the fix belongs in intake).

**Read these yourself**: `cli.py` `read_changes` and `_git_diff` (how a change reaches the impact engine, and the safety guards around running git).
