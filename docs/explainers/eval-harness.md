# Evaluation harness: acceptance suite, co-change benchmark, mutation truth

Modules: `eval/suite/`, `eval/cochange/`, `eval/mutants/`, and one additive change to `src/codeatlas/repo/cochange.py` (`read_history(..., rev=)`).
Run with `python -m eval.suite`, `python -m eval.cochange`, `python -m eval.mutants NAME`.

## What

Three measuring sticks, each answering one question:

| Stick | Question | Output |
| --- | --- | --- |
| **Acceptance suite** | Does CodeAtlas build a map of *any* repository, and what does it say about what it could not do? | `eval/results/suite_<date>.json` and `.md`: one row per pinned repository |
| **Co-change benchmark** | Given one changed file, can a predictor name the other files that changed with it? | `eval/results/cochange_<date>.json` and `.md` |
| **Mutation truth** | If this function breaks, which tests fail? | `eval/mutants/truth/<repo>_<sha12>.json` |

The suite has 47 pinned repositories (`repos.yaml`: name, URL, 40-character SHA, languages, size, one line of *why*), from a one-file C program to Django, TypeScript and Linux. The question-answering benchmark is not here (decision D-20).

## Why

- **Pinned SHAs.** A moving branch would make Monday's scoreboard incomparable with Friday's. The validator rejects a short SHA, an unknown size or a duplicate name.
- **A child process per repository.** The runner can kill a build that runs too long (a row with `timed out`, not a hang), and `ru_maxrss` of the child is exactly that build's peak memory. Rejected: building in-process (no hard time limit, memory is the max of all earlier builds). Peak memory is `null` on Windows, where the `resource` module does not exist.
- **Failures are rows.** A clone that fails, a crash and a timeout all become `status: error` with the stage and message, so one bad repository never hides the other 46. Rejected: raising (a night-long run would die at repository 3).
- **Resume by name.** Results are saved after every repository; a rerun on the same UTC day skips names already present. Rejected: resuming by file contents (more code for the same effect).
- **Clone through the intake, then `git checkout --detach <sha>`.** The intake only clones the default branch; the checkout pins the commit. The blobless clone keeps full history, which the co-change benchmark needs.
- **Co-change predictors share the repository layer's rules.** `CoChangePredictor` reuses `CoChangeAnalyzer._count` (same filters: vendored, lockfile, generated, not in the snapshot, over-large commits) and the same ranking (confidence, then support, then name). Rejected: a second copy of the rules (the benchmark could then drift from the product). It calls two private methods of the analyzer; I did not make them public because the brief allows only the `rev` change in that file (see the PR notes).
- **Mutation by text, on a scratch copy.** One simple edit per function; the original checkout is never written. Python uses `ast` to find the body (a regex cannot tell a docstring or a decorator from code); TypeScript matches the span's closing `}` to its opening `{` while skipping strings and comments, because a return type like `): { b: number } {` has a brace before the body's.
- **Unprovable mutants are kept.** A mutant no test notices stays in the file with `failing_tests: []` (the owner's Q4).

## How

### Acceptance suite

1. `load_repos` validates `repos.yaml`; `select` applies `--only`, `--max`, `--skip-large`.
2. For each repository: `clone_pinned` (intake clone, then checkout of the SHA; reused if HEAD already equals the SHA).
3. `python -m eval.suite.worker ROOT DB OUT SECONDS` in a subprocess with a wall-clock limit: `build_graph` into its own SQLite file, then read counts back with read-only SQL: files per tier and language, module nodes with `attrs["errors"]`, module nodes with `attrs["skipped_reason"]` grouped by reason, nodes and edges by kind, raw calls and how many are marked resolved, `limits_hit`, and `BuildResult.problems`.
4. The row is saved; the scoreboard is a markdown table plus totals.

Worked example (`click`, the first row of the run in the PR): 178 files, 91 deep (Python) and 87 text, no structural; 2 skipped; 2,267 nodes and 3,222 edges; 7,278 raw calls and 100% unresolved. That last number is true today: the Python and TypeScript resolvers (T06, T07) had not merged when this was measured, and the row's `problems` says three plugins did not load. The scoreboard is meant to show exactly that.

### Co-change benchmark

1. `recent_commits`: scan up to 10 × N non-merge commits (default N = 100), drop files by the analyzer's filters (checked against the tree *of that commit*), keep commits that still change 2 to 20 files. Each is held out.
2. One query per (commit C, file f in C); the truth is the other kept files of C.
3. A predictor gets `rev = C^` and may read only history reachable from it (`read_history(root, n, rev="C^")`). Both shipped predictors cache per `rev`, since every file of C shares it.
4. Scores, over all queries and per language of f (by extension):
   - **precision@k** = hits among the top k ÷ number predicted, over queries that got a prediction;
   - **recall@k** = hits among the top k ÷ size of the truth, over *all* queries (no prediction = 0);
   - **no-prediction share**.

Worked example (the test in `tests/eval/test_cochange_bench.py`): `pkg/a.py` and `pkg/b.py` change together in commits 1 to 3; commit 4 changes `pkg/a.py`, `pkg/b.py` and the new `other/x.py`. Query f = `pkg/a.py`, truth = {`pkg/b.py`, `other/x.py`}. Co-change (support 3) predicts [`pkg/b.py`]: precision 1, recall 0.5. Same-folder predicts [`pkg/b.py`, `pkg/old.py`] (most recently changed first): precision 0.5, recall 0.5. Query f = `other/x.py` is a new file: co-change has no history and predicts nothing, which counts in the no-prediction share and as recall 0.

### Mutation truth

1. `build_graph` the benchmark; candidates are FUNCTION nodes in Python or TypeScript/JavaScript with at least one caller, outside test files (`classify`). If the graph has no CALLS edge at all (no resolver registered yet), "has a caller" means another function's raw call has the function's name; the file records `caller_basis` so nobody mistakes the approximation for the real thing.
2. `pick`: sorted by key, `random.Random(seed).sample`, so a seed always gives the same functions.
3. Copy the folder to a scratch directory; run the unmutated tests first. If they do not run cleanly (exit status other than 0 or 1, or a timeout), stop: every mutant would look "caught".
4. For each function: write the mutant into the scratch copy, run the tests with a timeout, restore the file, and record failing ids that were not already failing in the baseline.
5. Write `<repo>_<sha12>.json` (a fixture folder uses its git tree hash instead of a commit).

Worked example: `backend/services.py::UserService.get_user` becomes `raise RuntimeError("mutant")`; `pytest backend` then fails two tests, and those two ids are the truth for "change `get_user`". On the fixture, 24 of 25 mutants fail at least one test; the survivor is `UserCard`, which no test renders.

Setup is not done by the harness (nothing is installed from a repository): `--venv DIR` puts a virtualenv's `bin` first on `PATH`, and `--node-modules DIR` links already installed packages into the scratch frontend.

## What each metric can hide

- **Suite**: "completed" only means no crash. A repository whose Kotlin files are all text tier completes. Read the tier columns and the unresolved share, not the status. The unresolved share is 100% until the resolvers merge, and later can look good if it simply counts calls into libraries as resolved externals.
- **Precision@k over queries with a prediction** looks great for a predictor that answers only when it is sure; the no-prediction share and recall over all queries expose it. The baseline "always has something to say" and so scores low precision but a low no-prediction share.
- **Held-out commits are not independent**: the files of one commit share one history, and large refactors dominate counts. The 2 to 20 file window removes both mass commits and one-file commits, so the benchmark says nothing about them.
- **Truth is "files that changed", not "files that had to change"**: a rename, a formatting sweep or a docs touch counts as truth. Co-change predicts habits well and dependencies partly.
- **Mutation truth**: a mutant no test catches has an empty failing list. The impact engine predicting a test there is scored as a false positive though the break is real, and predicting nothing is scored as perfect. Report caught and uncaught mutants separately and score the engine only on caught ones (or report both), and never merge them. On `itsdangerous`, `BadHeader.__init__` survived: it is exercised, but no assertion depends on what it stores.
- `raise RuntimeError` in the first line is a crude mutation: it fails every test that reaches the function, and so over-reports compared with a subtle bug that only a few tests would notice.

## Where

- Reads: `codeatlas.indexer.intake` (clone), `codeatlas.indexer.pipeline.build_graph`, `GraphStore`, `codeatlas.repo.cochange` (`CoChangeAnalyzer`, `read_history`, `parse_log`), `codeatlas.repo.test_conventions.classify`, `codeatlas.indexer.discover.language_for`.
- Contract types: `Node`, `Edge`, `FileRecord`, `Snapshot`, `Tier`, `NodeKind.FUNCTION`, `EdgeKind.CALLS`.
- T12 (impact engine) implements the `Predictor` protocol (`predict(repo_root, rev, changed_file, k) -> list[str]`) and is scored on the same queries against the two baselines; its test selection is scored against the mutation truth files.
- T14 uses the suite scoreboard as its regression gate: a resolver change must not raise `problems`, parse errors or the unresolved share on any row.
- T15's counting rules are the `cochange` predictor, so a change to them moves this benchmark's numbers.
