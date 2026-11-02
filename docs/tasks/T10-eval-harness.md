# T10: Evaluation harness: acceptance suite, co-change benchmark, mutation truth

**Wave**: 2 (all of Wave 2 runs in parallel)
**Branch**: keep the one the cloud environment gives you

## Goal

Three measuring sticks the later tasks are judged by:

1. **The acceptance suite**: about 40 pinned public repositories, from tiny to very large, in more than 12 languages, indexed one after another, with one scoreboard row each. This is how "works on any repository" (the owner's first requirement) becomes numbers.
2. **The co-change benchmark**: hold out recent commits and ask, from one changed file, which other files changed with it. It scores the impact engine on any language (T12).
3. **Mutation truth**: mutate one function in a pinned benchmark repository, run its tests, and record which tests fail. The failing tests are the truth the impact engine's test selection is scored against (T12).

The question-answering benchmark is not part of this task; it moves to after Nov 4 (proposal D-20 in `docs/decisions.md`).

## Files you may create or edit

- `eval/suite/`, `eval/cochange/`, `eval/mutants/` (new packages: code, config, the repository list)
- `src/codeatlas/repo/cochange.py`: one additive change only, an optional `rev` argument to `read_history` so history can stop before a held-out commit; keep every existing behaviour and test
- `tests/eval/` (new test modules)
- `docs/explainers/eval-harness.md`

Index with `build_graph` from `src/codeatlas/indexer/pipeline/` (read `docs/explainers/pipeline.md`). Do not edit `cli.py`: the entry points are `python -m eval.suite`, `python -m eval.cochange` and `python -m eval.mutants`. Everything under `eval/` must pass `ruff check .`, and its unit tests run in CI.

## Part 1: the acceptance suite (`eval/suite/`)

- `repos.yaml`: about 40 entries, each with `name`, `url`, a pinned full commit `sha` (look it up with `git ls-remote`), `languages`, `size` (small, medium, large, very large) and one line of `why` (what it tests: a monorepo, notebooks, generated code, vendored code, a language with no profile, Windows line endings, huge files...). Cover at least: Python, TypeScript, JavaScript, Go, Java, Rust, C#, PHP, Ruby, C, C++, Kotlin, Scala, Swift, Lua, Elixir, Shell, and a mixed frontend/backend repository. Include `pallets/click`. Keep most small or medium; three or four very large ones test the limits.
- The runner, for each repository: a blobless clone at the pinned commit through the existing intake (`codeatlas.indexer.intake`), then `build_graph` into its own database, inside a time limit. Record per repository: completed or the error, seconds, peak memory where the platform reports it, files per tier and per language, parse errors (module nodes with `attrs["errors"]`), skipped files by reason, nodes and edges by kind, raw calls and the unresolved share, `limits_hit`, and the build's `problems`.
- Output: `eval/results/suite_<UTC date>.json` and a markdown scoreboard `suite_<UTC date>.md` (one row per repository, then totals).
- `--only NAME`, `--max N`, `--skip-large`, and resume (skip repositories already in today's results).
- A clone that fails is a row with the error, never a crash; a repository is never built, installed or executed.

## Part 2: the co-change benchmark (`eval/cochange/`)

For a pinned repository with history: take the last N non-merge commits (default 100) that change between 2 and 20 files after the co-change filters. For each such commit C and each file f it changes, a predictor ranks other files using only history before C (`read_history(..., rev=C^)`). Truth: the other files C changed. Report precision and recall at 5 and at 10, overall and per language of f, and the share of queries with no prediction.

Define the predictor as a small protocol (`predict(repo_root, rev, changed_file, k) -> list[str]`) so the impact engine (T12) plugs in later; ship two predictors: co-change (from T15's counting rules) and a baseline (files in the same folder, most recently changed first). Run both on three repositories from the suite in different languages with real history; report the table.

## Part 3: mutation truth (`eval/mutants/`)

Only for repositories pinned in `eval/mutants/benchmarks.yaml`, and only inside the cloud VM or a container (CLAUDE.md, Safety: this is the one place repository tests run). Start with the fixture (`pytest backend`, `npx vitest run`) and one small Python repository with a fast test suite (choose it, pin it, say why).

- Pick functions from the indexed graph (FUNCTION nodes with at least one caller, skipping tests), at most N per repository (default 30), deterministic with a seed.
- Apply one simple mutation per function on a scratch copy: Python: replace the body with `raise RuntimeError("mutant")`; TypeScript: `throw new Error("mutant")` as the first statement. Never edit the original checkout.
- Run the repository's tests with a timeout; record the failing test ids. A mutant no test notices is kept, with an empty list: the owner's Q4 in `docs/decisions.md` is about exactly these.
- Output: `eval/mutants/truth/<repo>_<sha12>.json` with, per mutant, the function key, the mutation, the failing test ids, the run time and the test command's exit status.
- On Windows, the runner says it is for the cloud VM and stops.

## Tests

Offline and fast: `repos.yaml` validates (unique names, 40-character SHAs, known sizes); the suite runner on two local repositories built in the test (one fine, one whose clone fails); the scoreboard's markdown; the co-change benchmark on a repository built in the test with scripted commits and known answers for both predictors; mutant selection is deterministic; the mutation of a Python and a TypeScript function (on text, no test run); the Windows refusal. Tests that clone or run real test suites are marked `@pytest.mark.live`.

## Measure and report

In the pull request: the suite run on at least 5 repositories (from small to large, at least 4 languages) with the scoreboard; the co-change table on 3 repositories; mutation truth for the fixture and the chosen Python repository (mutants made, mutants caught by at least one test, time). If cloning fails in the cloud session, say so with the exact error (try twice), and run what you can on local repositories.

## Done when

Tests pass on Linux and Windows CI; the three reports are in the pull request; the explainer covers each benchmark with a worked example, what each metric can hide (for example, a mutant no test catches), and how T12 and T14 will use them.
