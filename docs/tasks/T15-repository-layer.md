# T15: Repository layer

> **Reading note.** This brief is history. It is what a cloud session was told to build, kept so you can see what was asked; it is not an instruction for new work.
> - **Built in**: pull request #9, with fixes in #19.
> - **Read first**: `docs/explainers/repository-layer.md`, for what was actually built and why.
> - **Code**: `src/codeatlas/repo/`. **Tests**: `tests/repo/`.
> - **Then** read this brief and its review at the end: the gap between them is where the interesting questions are.
> - Reading order, glossary and how to study a module: `docs/README.md`.

**Wave**: 1 (parallel with T01 to T05)
**Branch**: `task/T15-repository-layer`

## Goal

Give every repository, in any language, the facts that need no parser: which packages it declares and how they depend on each other, which files belong to which package, which test files cover which source files by naming convention, and which files change together in git history. This layer is what makes CodeAtlas useful on a repository whose languages have no deep support yet.

Implement each part as a `RepoAnalyzer` (contract section 7). Analyzers may read files and run read-only `git` commands. They never run build tools, package managers, `setup.py` or any repository code.

## Files you may create or edit

- `src/codeatlas/repo/` (any modules inside it), with `default_analyzers()` in `repo/__init__.py`
- `tests/repo/`, `tests/data/repo/`
- `docs/explainers/repository-layer.md`

## Part 1: manifests and packages (`repo/manifests.py`)

Parse manifests statically into PACKAGE nodes (key format in contract section 4), DEPENDS_ON edges between packages of the same repository, and CONTAINS edges from each package to the module nodes of the files under its root (the deepest package root wins; module node ids come from `make_node_id(snapshot_id, make_key(path, ""))`).

| Ecosystem | Manifests | Package name | Workspace members | Internal dependencies |
| --- | --- | --- | --- | --- |
| npm, yarn, pnpm | `package.json`, `pnpm-workspace.yaml` | `name` | `workspaces` globs; pnpm `packages` globs | dependencies naming another workspace package, including `workspace:` versions |
| Python | `pyproject.toml` (`[project]` or `[tool.poetry]`), `setup.cfg`; `setup.py` only through a regex for a literal `name=`, never executed | as declared | `[tool.uv.workspace] members` | dependencies naming another package in the repo |
| Go | `go.mod`, `go.work` | module path | `go.work` `use` directories | `require` lines naming another module in the repo |
| Rust | `Cargo.toml` | `[package] name` | `[workspace] members` | `path` dependencies and workspace members |
| Maven | `pom.xml` | `groupId:artifactId` | `<modules>` | `<dependency>` on another module's artifact |
| Gradle | `settings.gradle(.kts)`, `build.gradle(.kts)` | project path | `include(...)` | `project(":x")` dependencies, found by regex |
| .NET | `*.sln`, `*.csproj` | project file name | solution entries | `<ProjectReference>` |
| PHP | `composer.json` | `name` | path repositories | `require` naming another package in the repo |

Also record in each package's `attrs`: `ecosystem`, `manifest`, `version` when declared, `root` (directory), and `entry_points` where easy to find (`package.json` `main`/`bin`, `[project.scripts]`, Go directories with `package main`, Cargo binaries). Record PHP's PSR-4 `autoload` map and Go's module path in `attrs` as well; T16's resolution profiles will read them.

A repository with no manifest gets one implicit package rooted at the repository root, named after the repository, with `attrs["implicit"] = True`, so every module belongs to some package.

Use `tomllib`, `json` and `xml.etree.ElementTree` from the standard library and `pyyaml` (declared in T00) for YAML. A manifest that fails to parse is recorded as a warning in the package's `attrs["warnings"]`; it never stops the analysis.

## Part 2: test conventions (`repo/test_conventions.py`)

Detect test files by path and name, and pair each with the source file it most likely tests. Emit TESTS edges from the test file's module node to the source file's module node, with resolution `CONVENTION` and confidence 0.8, or 0.8 divided by the number of equally good candidates.

| Language | Test file patterns | Pairing hints |
| --- | --- | --- |
| Python | `test_*.py`, `*_test.py`, files under `tests/` | `tests/test_user.py` → `user.py` in the same package |
| TypeScript, JavaScript | `*.test.*`, `*.spec.*`, `__tests__/` | strip `.test` / `.spec` |
| Go | `*_test.go` | same directory |
| Java, Kotlin | `*Test`, `*Tests`, `*IT`; `src/test/...` | mirror `src/test/java` to `src/main/java` |
| C# | `*Tests.cs`; projects ending `.Tests` | mirror the project without `.Tests` |
| Ruby | `*_spec.rb`, `*_test.rb`; `spec/`, `test/` | mirror into `lib/` or `app/` |
| PHP | `*Test.php`; `tests/` | mirror into `src/` |
| Rust | files under `tests/` | the crate's `src/lib.rs` |
| C, C++ | `test_*.c*`, `*_test.c*`, `tests/` | strip the affix, any directory in the same package |

Prefer candidates in the same package, then the nearest directory. Unpaired test files are listed in the analyzer's summary, not treated as errors.

## Part 3: co-change (`repo/cochange.py`)

From `git log --no-merges --no-renames --name-only` over the last `max_history_commits` commits reachable from HEAD (config from T00, default 2,000), compute for each ordered pair of files (a, b):

- `support` = commits that changed both
- `confidence` = support ÷ commits that changed a

Emit CO_CHANGES edges a → b with resolution `HISTORY`, the confidence, and `attrs` `support` and `source_commits`, when support is at least 3 (configurable), keeping the 20 strongest targets per source file.

Filters, each configurable and each counted in the summary:

- skip commits that touch more than 50 files (formatting sweeps, mass renames, version bumps)
- ignore lockfiles (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `poetry.lock`, `uv.lock`, `Cargo.lock`, `go.sum`, `composer.lock`), minified and generated files, and anything under `vendor/`, `dist/`, `build/` or `node_modules/`
- ignore files that no longer exist at HEAD

The blobless clone from T00 keeps the full history, and `--no-renames` lets git list changed paths without downloading old file contents. A folder that is not a git repository, or a clone with no history, yields no co-change edges and says so in the summary.

## Part 4: summary

`summarize(files, nodes, edges) -> dict` for the CLI and the acceptance suite: language census from the `FileRecord`s, packages per ecosystem, test files found and paired, co-change edges, commits analysed, and how many commits and files each filter removed.

## Tests

- `tests/data/repo/`: one small synthetic monorepo per ecosystem in the table, each with two or three packages and one internal dependency; assert packages, DEPENDS_ON and CONTAINS edges, including the implicit package for a repo without manifests
- test-convention pairing for every row of the table, including an ambiguous case that splits confidence
- co-change on a temporary git repository the test builds with scripted commits: exact confidences, the large-commit filter, the lockfile filter, a deleted file, and a non-git folder
- a malformed manifest produces a warning, not an exception
- no test uses the network

## Real-repository check

If the cloud session can clone public repositories, run all three analyzers on three repositories from different ecosystems that have several packages or modules (choose them; prefer medium-sized ones), and report in the pull request: packages found, internal dependencies, test pairing rate, co-change edges and run time. If cloning fails, say so; that is information, not a blocker.

## Done when

All tests pass on Linux and Windows CI; the real-repository check is reported; the explainer covers each analyzer's What, Why, How and Where, including why co-change is directional and what its filters can wrongly remove.

## Notes from T00 (read before starting)

- **Configuration**: `Config.max_history_commits` already exists in `src/codeatlas/config.py` (default 2,000, from `[history]` in `codeatlas.toml`). Read it from there.
- **Test helpers**: reuse the `make_repo` fixture and the `git` helper in `tests/conftest.py` to build repositories with scripted commits.
- **Parent repositories**: a test that runs git in a temporary folder must not see a git repository in a parent folder. The owner's home folder is one, and that broke a T00 test on his machine. In your git-based tests, set the environment variable `GIT_CEILING_DIRECTORIES` to the temporary folder's parent, for example in a fixture in `tests/repo/conftest.py`.
- **Where to plug in**: `src/codeatlas/repo/__init__.py` exists with only a docstring; add `default_analyzers()` there.
- **Sample files**: pytest does not collect anything under `tests/data/`, so sample repositories with files like `test_user.py` are safe there.

## Review of PR #9 (Oct 30)

**Verdict**: merge after fixes (one must fix, about 15 lines). **Fixes**: issue #16. Paste it into the T15 session (cross out part 5 first if you reject decision D-12), wait for CI, then merge.

**What the PR does**: three `RepoAnalyzer`s that need no parser. Manifests become PACKAGE, CONTAINS and DEPENDS_ON for 8 ecosystems, parsed statically; test files are paired with source files by name (TESTS at 0.8, ties share it); `git log` gives directional CO_CHANGES edges, with each filter's removals counted. `summarize()` and `default_analyzers()` tie them together. Well built, thorough tests, an unusually good explainer.

| Check | Result | Evidence |
| --- | --- | --- |
| Scope | PASS | 91 files, all inside the brief |
| Contract untouched | PASS | No diff in `models.py` or `indexer/adapter.py` |
| Tests | PASS | 239 passed (95 new); all 95 still pass with temp folders inside a parent git repository |
| Lint | PASS | `ruff check .` clean |
| Mutation spot-check | WARN | 11 of 14 caught; three survivors become tests in issue part 3 |
| Explainer | PASS | A worked example per analyzer and a table of what each filter can wrongly remove |
| Brief coverage | PASS | Every ecosystem, every pairing row, ambiguity, malformed manifests, every filter, a non-git folder, 4 real repositories |
| Safety | PASS | Only read-only git (`rev-parse`, `log`); YAML with `safe_load`; `setup.py` read by regex, and a test proves it never runs |
| Silent gaps | WARN | One bad manifest wipes out its ecosystem (must fix 1); an unreadable Go file is skipped without a record |

**On this repository**: 71 files, 1 package (`codeatlas`, entry point `codeatlas = codeatlas.cli:main`), 5 of 14 test files paired, 0 co-change edges (only 7 commits; none pair reaches the support of 3). All three analyzers together take 0.03 s. Co-change becomes interesting on a repository with real history, such as click.

**Must fix** (issue #16, part 1)
1. `manifests.py:84-91`: an exception in one manifest drops every package of its ecosystem; the reviewer showed two `composer.json` files vanishing because one had a bad value. Catch errors per manifest, so the bad one still becomes a package carrying its warning.

**Should fix** (issue #16, parts 2 to 4)
1. Record why something was skipped (an unreadable file, git missing or timing out); today a missing git on Windows reads as "not a git repository".
2. Tests for the three mutation survivors and CRLF `git log` output; one shared ceiling fixture in `tests/repo/conftest.py`.
3. `repo/test_conventions.py` is itself classified as a test, so its test file can never pair with it.

**Your decisions** (the PR's twelve, then two from the review; write your answer next to each)

| # | Question | Recommendation |
| --- | --- | --- |
| 1 | `summarize` takes an optional `analyzers` parameter | Accept |
| 2 | The implicit package also takes leftover files | Accept |
| 3 | Every manifest is a package | Accept, with decision A |
| 4 | Broken or nameless manifests still make a package | Accept |
| 5 | Implicit package key `::package:<repo>` with an empty path | Accept; T18 checks the store and viewer handle it |
| 6 | A shared name splits DEPENDS_ON confidence | Accept |
| 7 | `source_commits` is a count | Accept |
| 8 | Co-change only at a repository's top level | Accept |
| 9 | Filter settings are constructor arguments | Accept; move them into `[history]` config later |
| 10 | Pairing choices beyond the table | Accept, with should fix 3 |
| 11 | Gradle projects named by project path | Accept |
| 12 | Extra attrs (PSR-4 map, Go module path) | Accept; T16 confirms the shape |
| A | Fixture and vendored manifests count as packages: this repository shows 31 packages, 30 from `tests/data/repo`, and a committed `vendor/` makes a library "internal" | Add `attrs["role"]` (package, fixture, vendored); no DEPENDS_ON into vendored; count real packages separately (D-12, issue part 5) |
| B | Should Python test detection read `[tool.pytest] testpaths`? | No; should fix 3 is simpler |

**Try it yourself** (PowerShell, after `gh pr checkout 9`)

```powershell
python -m pytest -q tests/repo
python -c 'from pathlib import Path; from codeatlas.config import Config; from codeatlas.indexer.discover import discover; from codeatlas.indexer.registry import Registry; from codeatlas.models import make_snapshot_id; from codeatlas.repo import default_analyzers, summarize; r = Path.cwd(); f = discover(r, Config(), Registry().tier_for).files; a = default_analyzers(); out = [x.analyze(r, f, make_snapshot_id(r.name, 12 * str(0))) for x in a]; n = [y for o in out for y in o[0]]; e = [y for o in out for y in o[1]]; [print(v) for v in list(summarize(f, n, e, a).values())[1:]]'
```

Expect `95 passed`, then three lines: packages (31 in total, 30 from the test fixtures: decision A in action), test pairing (51 test files, 8 paired), and co-change (0 edges; the commit counts follow your local history).

**Read these yourself**
- `src/codeatlas/repo/cochange.py:92-159` (`_count`, `_edges`): the filter order and directional confidence the impact engine (T12) will weigh; compare with your answer to Q5.
- `src/codeatlas/repo/test_conventions.py:194-222` (`_best_candidates`, `_rank`): this ranking decides every TESTS edge and every tie.
- `src/codeatlas/repo/manifests.py:74-106, 177-198`: file ownership, the implicit package, and the guard behind must fix 1.
