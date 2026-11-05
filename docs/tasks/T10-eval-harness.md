# T10: Evaluation harness: acceptance suite, co-change benchmark, mutation truth

> **Reading note.** This brief is history. It is what a cloud session was told to build, kept so you can see what was asked; it is not an instruction for new work.
> - **Built in**: pull request its session opened no pull request; its branch was merged in #27.
> - **Read first**: `docs/explainers/eval-harness.md`, for what was actually built and why.
> - **Code**: `eval/suite/`, `eval/cochange/`, `eval/mutants/`. **Tests**: `tests/eval/`.
> - **Then** read this brief and its review at the end: the gap between them is where the interesting questions are.
> - Reading order, glossary and how to study a module: `docs/README.md`.

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

## Review of the T10 branch (Nov 3)

**Verdict**: merge after fixes; merged and fixed in the "Wave 2 review fixes" pull request. The session pushed its branch but never opened a pull request, most likely because it ran out of credit after its last commit.

**What it built**: `python -m eval.suite` (47 pinned repositories, each built in a child process with a time limit, a JSON and markdown scoreboard, resume); `python -m eval.cochange` (held-out commits, precision and recall at 5 and 10, a `Predictor` protocol for T12, co-change and same-folder predictors); `python -m eval.mutants` (pinned benchmarks only, scratch copies only, a baseline check first, timeouts). Co-change beats the same-folder baseline on click (P@5 0.27 vs 0.12), cobra (0.30 vs 0.19) and express (0.43 vs 0.33).

**Must fix (done)**: the mutator broke `@overload` stubs whose body shares the header's line, so three itsdangerous "caught" mutants were really syntax errors. It now skips overloads and any mutation that no longer parses, and both truth files were regenerated on the merged tree (caller basis `calls-edges`): itsdangerous 29 made, 29 caught; fixture 23 made, 22 caught. A test assumed no resolvers existed; fixed. The committed scoreboard predated Wave 2 (100% unresolved everywhere); re-run on the merged tree, see `docs/history/wave3.md`.

**Also fixed**: the Windows refusal is in `run_benchmark` itself; the message no longer suggests WSL (CLAUDE.md says cloud VM or container); the pin check raises instead of `assert`; a failed co-change clone is a row with its error.

**Still open**: kill the whole process group on a test timeout; `eval/cochange` calls T15's private `_count` and `_filter_reason` (make them public in a later task); Kotlin and Bash files land in the text tier with no recorded reason (Kotlin has no grammar in `pyproject.toml`; Bash has none either), which the suite scoreboard shows.

**Your decisions**: mutation truth runs only in the cloud VM or a container (done); T12 is scored on `calls-edges` truth (done); T12 builds one index and reads history up to each commit, rather than re-indexing per commit (in the T12 brief).

**Read these yourself**: `eval/mutants/mutate.py` (the mutator and its new checks); `eval/mutants/run.py` (the only place repository tests run); `eval/cochange/predictors.py` (the protocol T12 implements).
