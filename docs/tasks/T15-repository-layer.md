# T15: Repository layer

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
