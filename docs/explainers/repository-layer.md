# Repository layer

Modules: `src/codeatlas/repo/` (`manifests.py` with one parser per ecosystem in
`ecosystems/`, `test_conventions.py`, `cochange.py`, `summary.py`, `paths.py`), and
`default_analyzers()` in `repo/__init__.py`.

## What

Three analyzers give every repository, in any language, facts that need no parser:

| Analyzer | Produces | From |
| --- | --- | --- |
| `ManifestAnalyzer` (`"manifests"`) | PACKAGE nodes, CONTAINS (package → module), DEPENDS_ON (package → package) | `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `pom.xml`, Gradle files, `.csproj`/`.sln`, `composer.json` |
| `TestConventionsAnalyzer` (`"test_conventions"`) | TESTS edges (test module → source module), confidence 0.8 | file names and folders |
| `CoChangeAnalyzer` (`"cochange"`) | CO_CHANGES edges (module → module), confidence from history | `git log` |

`summarize(files, nodes, edges, analyzers)` turns their output into one dictionary for
the CLI and the acceptance suite: language census, packages per ecosystem, test files
found and paired, co-change edges, commits read, and what each filter removed.

Each analyzer also keeps a `report` dictionary from its last run (for example the
co-change status such as "not a git repository" or "git not found", or the list of unpaired test files).

## Why

### Manifests

- **Read, never run.** `setup.py` and Gradle build files are programs. Running them
  could do anything, so CodeAtlas reads them with regexes: `setup.py` only through a
  literal `name="..."`, Gradle only through `include(...)`, `project(":x")` and
  `projects.x` accessors. A test writes a `setup.py` that would create a file if
  executed and checks that the file never appears.
- **One parser per ecosystem, one orchestrator.** Every ecosystem has a different file
  format, but what happens after parsing is the same: match dependencies to packages,
  mark workspace members, decide which package owns each file. So each parser
  (`ecosystems/npm.py`, ...) only reports `Declared` packages and `Workspace`s, and
  `manifests.py` does the rest once. Rejected: a class hierarchy with one subclass per
  ecosystem; plain modules with one `find(view)` function are easier to read.
- **Every manifest is a package, even outside a workspace.** A `package.json` in
  `examples/demo/` is a package whether or not the root lists it. Workspace membership
  is recorded in `attrs["workspace"]` instead of deciding whether a package exists.
  Rejected: trusting only workspace globs, which would drop example apps and nested
  tools silently.
- **A broken manifest becomes a warning.** A `package.json` that does not parse still
  marks a package, named after its folder, with the error in `attrs["warnings"]`. A
  broken file that is not itself a package (`pnpm-workspace.yaml`) puts its warning on
  the package that contains it. If a parser has a bug and raises, only that manifest is
  affected (`guarded` in `ecosystems/base.py`): its half-done work is discarded and it
  still becomes its own folder-named package carrying the error, so its files are not
  handed to the implicit package. A whole ecosystem can no longer vanish because of one
  bad file.
- **Packages have a role (decision D-12).** A manifest under `vendor/`, `third_party/`
  or `node_modules/` is `vendored`; one under a test or fixture folder (`tests/`,
  `testdata/`, `fixtures/`, `eval/fixtures/`) is a `fixture`; everything else is a
  `package`. Every one stays a node, but no DEPENDS_ON edge points into vendored code,
  and the summary reports `real` packages separately: CodeAtlas itself has 31 manifests,
  30 of them test samples.
- **An implicit package for whatever no manifest covers.** A repository without
  manifests gets one package at the root, named after the repository, with
  `attrs["implicit"] = True`. The same package also collects files outside every
  declared package (root scripts beside `packages/*`), so every module belongs to
  exactly one package.
- **Dependencies by path beat dependencies by name.** `"lib": "file:../lib"`, Cargo's
  `path = "../lib"`, Go's `replace x => ../lib` and .NET's `<ProjectReference>` point at
  a folder, so they are exact. A dependency by name links to every package in the
  repository with that name. If two packages share it (two example apps both named
  `demo`), each edge gets confidence 1/2 and `attrs["candidates"] = 2`.
- **Names are compared the way each ecosystem compares them**: PEP 503 for Python
  (`Acme_Core` = `acme-core`), `-`/`_` for Cargo, case-insensitive for .NET and Composer.

### Test conventions

- **Naming habits read backwards.** `test_user.py` says "I test `user`", so the analyzer
  strips the affix and looks for `user.py`. It is cheap, works without a parser and is
  right surprisingly often. Its confidence is 0.8, not 1.0, because a name is a hint. A
  module named like a test but outside every test folder (this layer's own
  `test_conventions.py`) is also a candidate source, so its real test can pair with it.
- **Support files are counted but not paired.** `tests/conftest.py` or
  `tests/helpers.py` is a test file, but its name says nothing about what it tests, so
  it is listed as unpaired instead of being matched to some `helpers.py` elsewhere.
  JavaScript (`__tests__/user.js`, mocha's `test/user.js`) and Rust (`tests/*.rs`) are
  exceptions, because their conventions use no affix.
- **Ranking before splitting.** Several `user.py` files are common. The candidates are
  ranked; only the ones that tie for best share the confidence, 0.8 ÷ n. Rejected:
  splitting across every same-named file, which would turn one clear pairing into many
  weak ones whenever a name such as `utils.py` repeats.
- **Code beats declarations.** A C header or a Python type stub (`.pyi`) is ranked
  below the code it declares. Without this, every test in pydantic/logfire tied between
  `logfire/x.py` and its stub `logfire_api/x.pyi` (52 of 60 pairings were ambiguous);
  with it, none are.

### Co-change

- **Directional.** Confidence is support ÷ commits that changed the *source* file. A
  small helper `fmt.py` changed 4 times, always with `core.py`, gets 4/4 = 1.0 towards
  `core.py`; `core.py`, changed 40 times, gets 4/40 = 0.1 back. "When fmt changes, core
  changes" is a strong signal; "when core changes, fmt changes" is not. One number for
  the pair would hide that, so a pair gives two edges.
- **Minimum support of 3.** One or two shared commits are coincidence; three repeat.
- **20 strongest targets per file**, so a file touched by everything does not produce
  thousands of edges (trpc: 1,786 weaker targets dropped and counted).
- **History must belong to the folder.** Co-change runs only when the folder is the top
  of its own git repository. A plain folder inside another repository (the owner's home
  folder is one) would otherwise borrow that repository's history.
- **`--no-renames`.** Git can list changed paths from trees alone; rename detection
  would need old file contents, which a blobless clone does not have. The cost: history
  before a rename stays with the old name (see Known limitations).

What the filters remove, and what they can wrongly remove:

| Filter | Removes | Can wrongly remove |
| --- | --- | --- |
| Commits touching more than 50 files | formatting sweeps, mass renames, licence headers, version bumps | a real large refactor, such as an API change applied across 60 files at once |
| Lockfiles (`package-lock.json`, `go.sum`, ...) | files that change with every dependency bump | nothing useful: a lockfile is never the file someone asks about |
| Minified and generated files (`.min.js`, `.map`, `_pb2.py`, `.pb.go`, `*.generated.*`) | output that changes whenever its source does | the generated code itself, when someone does ask "what changes with `api_pb2.py`?" |
| `vendor/`, `dist/`, `build/`, `node_modules/` | copied or built code | a project whose real source lives in a folder named `build/` (a build tool's own repository) |
| Files not in the snapshot | deleted or renamed files | the history of a file that was renamed: it lives on under its old name, which is dropped |

Each filter is a constructor argument of `CoChangeAnalyzer`, and each one's effect is
counted in the report.

## How

### Manifests, step by step

1. `RepoView` wraps the snapshot's `FileRecord`s, so a parser only reads files that are
   in the snapshot (never `node_modules/`, which discovery already skipped).
2. Each ecosystem's `find(view)` picks its manifests by file name, parses them with
   `json`, `tomllib`, `xml.etree.ElementTree`, `configparser`, `yaml.safe_load` or a
   regex, and returns `Declared` packages and `Workspace`s.
3. Workspaces: each member glob is joined to the workspace's folder and matched against
   every package root of the same ecosystem (`*` stays in one folder, `**` crosses
   folders, `!glob` excludes).
4. File ownership: for each file, walk up its folders until one is a package root. If
   two packages share that root, the one whose ecosystem fits the file's language wins.
5. Files with no owner go to the implicit package.
6. Dependencies: path dependencies first, then names; DEPENDS_ON edges with resolution
   `STRUCTURAL`.

Worked example (`tests/data/repo/npm/`):

```
package.json                  {"private": true, "workspaces": ["packages/*"]}
packages/api/package.json     {"name": "@shop/api", "main": "src/index.js",
                               "dependencies": {"@shop/core": "workspace:*", "express": "^4"}}
packages/api/src/index.js
packages/core/package.json    {"name": "@shop/core"}
packages/core/index.js
```

- The root `package.json` has workspaces but no name: a workspace, not a package.
- `@shop/api` and `@shop/core` are packages; both match `packages/*`, so both get
  `attrs["workspace"] = "package.json"`.
- `@shop/api` depends on `@shop/core` (a name in this repository) and `express` (not in
  the repository, so no edge). Result: one DEPENDS_ON edge, confidence 1.0.
- The root `package.json` file has no package above it, so the implicit package `npm`
  contains it. `packages/api/src/index.js` belongs to `@shop/api`.
- The node for `@shop/api`: key `packages/api/package.json::package:@shop/api`,
  `attrs = {ecosystem: "npm", manifest: "packages/api/package.json", root: "packages/api",
  entry_points: ["packages/api/src/index.js"], version: "1.2.0", workspace: "package.json"}`.

### Test conventions, step by step

1. `classify(path, language)` applies the rule for the language family:

   | Family | Test file | Subject |
   | --- | --- | --- |
   | Python | `test_X.py`, `X_test.py`; other files under `tests/` are support files | `X` |
   | JS/TS | `X.test.*`, `X.spec.*`; any file under `__tests__/`, `test/`, `spec/` | `X` |
   | Go | `X_test.go` (pairs only in the same folder) | `X` |
   | Java, Kotlin | `XTest`, `XTests`, `XIT`; other files under `src/test` are support | `X` |
   | C# | `XTests.cs`, `XTest.cs`; other files in a `*.Tests` project are support | `X` |
   | Ruby | `X_spec.rb`, `X_test.rb`, `test_X.rb` | `X` |
   | PHP | `XTest.php` | `X` |
   | Rust | any file under `tests/` | the crate's library (`[lib] path` or `src/lib.rs`), else its binaries |
   | C, C++ | `test_X.c*`, `X_test.c*`, `X_unittest.c*` | `X` |

2. Candidates are the non-test files of the same family whose stem is `X`.
3. Each candidate gets a rank; lower is better, compared left to right:
   `(other package?, −shared folder layout, declaration file?, folder steps apart)`.
   The *shared layout* counts trailing folders the two paths share after removing
   folders like `tests`, `src`, `main`, `java`, `unit`, and a `.Tests` suffix:
   `src/test/java/com/acme/MoneyTest.java` and `src/main/java/com/acme/Money.java`
   share `com/acme`.
4. All candidates with the best rank get a TESTS edge, confidence 0.8 ÷ their number.

Worked example: `tests/Unit/Models/UserTest.php` with `src/Models/User.php` and
`src/Http/User.php`. Subject `User`, two candidates, same package. Layouts:
`[models]` for the test, `[models]` and `[http]` for the candidates. `src/Models/User.php`
shares one folder, the other none, so it wins alone: one edge, confidence 0.8.

### Co-change, step by step

1. `git rev-parse --show-toplevel` must name the analysed folder itself; otherwise the
   status says why and there are no edges. A repository with no commits says so too.
2. `git log --no-merges --no-renames --name-only --format=<RS>%H --max-count=2000 HEAD`
   lists each commit's changed paths. (RS is the ASCII record separator, which no path
   contains, so commits are split safely.)
3. Commits with more than 50 paths are skipped. Every other path is checked against the
   filters, first match wins: vendored folder, lockfile, generated, not in the snapshot.
4. For each remaining commit: every file's count goes up by one, and so does every
   unordered pair's.
5. Every pair with support ≥ 3 gives two candidates, `a → b` with `support / count[a]`
   and `b → a` with `support / count[b]`. Each file keeps its 20 strongest.

Worked example (from `tests/repo/test_cochange.py`):

| commit | changed |
| --- | --- |
| 1 | a.py, b.py, c.py |
| 2 | a.py, b.py |
| 3 | a.py, b.py |
| 4 | a.py |
| 5 | b.py, c.py |
| 6 | b.py |

Counts: a 4, b 5, c 2. Pairs: a+b 3, b+c 2, a+c 1. Only a+b reaches support 3:

- `a.py → b.py`: 3 / 4 = 0.75, `attrs = {support: 3, source_commits: 4}`
- `b.py → a.py`: 3 / 5 = 0.6, `attrs = {support: 3, source_commits: 5}`

With `min_support=2`, `c.py → b.py` would be 2 / 2 = 1.0 and `b.py → c.py` only 0.4.

## Where

- **Contract types**: `RepoAnalyzer` (`indexer/adapter.py`) is the protocol all three
  satisfy. They read `FileRecord`s and return `Node`s (kind `PACKAGE`) and `Edge`s with
  `EdgeKind` CONTAINS, DEPENDS_ON, TESTS, CO_CHANGES and `Resolution` STRUCTURAL,
  CONVENTION, HISTORY. Ids come from `make_key` and `make_node_id`; a module id is
  `make_node_id(snapshot_id, make_key(path, ""))`, exactly what the adapters create.
- **Config**: `Config.max_history_commits` (`config.py`, `[history]` in
  `codeatlas.toml`) sets the co-change window through `default_analyzers(config)`.
- **Inputs**: discovery (`indexer/discover.py`) provides the `FileRecord`s and has
  already left out `node_modules/`, `dist/` and the like; intake's blobless clone
  provides the history.
- **Consumers**: the store (T03) persists the nodes and edges; T16's resolution profiles
  read `attrs["module_path"]` (Go) and `attrs["autoload_psr4"]` (PHP); the impact engine
  (T12) uses CO_CHANGES and TESTS; the CLI and the acceptance suite print `summarize`.
- `test_conventions.py` calls `manifests.find_packages` itself for the "same package"
  rule, so the three analyzers can run in any order.

## Real-repository check (Windows, 2026-10-30)

| Repository | Files | Packages | Internal deps | Tests paired | Co-change edges | Analyzer time |
| --- | --- | --- | --- | --- | --- | --- |
| BurntSushi/ripgrep (Cargo) | 226 | 11 cargo | 18 | 15/15 (100%) | 867 | 0.18 s |
| trpc/trpc (pnpm) | 1,656 | 55 npm | 136 | 231/454 (51%) | 2,520 | 0.39 s |
| pydantic/logfire (uv) | 1,039 | 4 pypi + 1 npm | 2 | 60/150 (40%) | 1,546 | 0.21 s |
| square/retrofit (Gradle) | 1,110 | 28 gradle + 1 npm | 33 | 36/144 (25%) | 806 | 0.22 s |

Unpaired tests are mostly support files (`conftest.py`, `__init__.py`, sample code
under `tests/`) and tests named after behaviour rather than a file (`smoke.test.ts`,
retrofit's `ListenableFutureTest` for `GuavaCallAdapterFactory`). No naming rule can
pair those; the impact engine should lean on import edges for them.

## Known limitations

- Gradle: `project(...)` paths, `projects.x` accessors and `include(...)` are read by
  regex; a project directory moved with `project(":x").projectDir = ...` or included
  through `includeBuild` is not followed, and a Groovy `include` list split over lines
  without parentheses is cut at the first line.
- Maven: `${...}` is filled in only from the pom's own properties and its parent's
  groupId and version, not from a parent pom elsewhere or from profiles.
- npm: `catalog:` versions (pnpm catalogs) and `nohoist` are not interpreted; a
  dependency is internal only when its name or `file:`/`link:` path matches.
- Test pairing is by file name only; a test of several files pairs with at most the
  ones named like it. Go tests pair only with a same-named file in the same folder.
- Co-change does not follow renames, so a renamed file starts with no history; its old
  history is counted under `not_in_snapshot` (which also counts files discovery left
  out, such as `.venv/`). A shallow clone has one commit and yields no
  edges (the report says `shallow: true`).
- `summarize` reads module paths out of edge ids, which relies on snapshot ids
  containing no `/` (true for `make_snapshot_id` with a short repository name).
- `TestConventionsAnalyzer` reads the manifests a second time; on very large
  repositories with many Go files this costs one extra pass over the Go files' first
  16 KB (for `package main` entry points).

## References: files that name other files (D-62, Nov 25)

**What.** `ReferenceAnalyzer` (`repo/references.py`) reads every text file and adds one REFERENCES
edge to each other file its text names: a README and its images, a workflow and
`requirements.txt`, a navigation file and its pages.

**Why.** Imports and calls join code to code; everything else floated. The owner saw `.gitignore`,
`README.md` and `images/` under "Not connected here". Measured on five repositories, files with
no edge but containment, before and after:

| Repository | Files | Floating before | After |
| --- | --- | --- | --- |
| PitwallOS | 269 | 122 | 40 |
| Antidote graph-hacks | 112 | 29 | 2 |
| cli (GitLab) | 1,853 | 379 | 127 |
| itsdangerous | 50 | 23 | 6 |
| logfire | 1,091 | 572 | 116 |

What still floats is named nowhere (`.gitignore`, issue templates). Those are found by their text
instead (`intake-and-discovery.md`, D-59).

**How.** A name is looked up the way a reader would, and each way has its confidence:

1. A path, next to the file that holds it, then from the root: 1.0 (`direct`).
2. A bare file name, next to it or at the root: 0.8 (`convention`).
3. A bare name or a path ending that only one file has: 0.3 (`name_guess`).
4. A folder of at most 20 files: 0.3 or 1 ÷ its files, whichever is smaller, for each.

A name two files have is not guessed. The surest way per pair wins, with its line. Code naming code
is left out, because imports and calls say that better: at least one end is a text-tier file. Files
that may hold secrets, binaries, minified files and files over 500 kB are not read.

Example: `docs/guide.md` line 2 holds `![chart](images/chart.png)`; `docs/images/chart.png` exists,
so the edge is `docs/guide.md` to `docs/images/chart.png`, 1.0, `direct`, line 2.

**What an edge claims.** That the file is named, not that it is used. The impact engine does not
follow it. On the map it is drawn in grey and the tooltip says "names"; `get_imports` gives the
agent `names` and `named_by`.

**How good it is.** The fixture's answer key has no references, so its score does not cover them
(38 edges are listed as not scored; everything else is unchanged at precision 1.000). Read by hand,
a random sample of 60: all 40 at 1.0 and 0.8 name the file; 18 of 20 guesses do. The two wrong ones:
`logfire/{VERSION}` in a User-Agent string, and a test that writes its own `package.json`.

**Where.** Tests: `tests/repo/test_references.py` (nine), the arrow in `test_web_diagram.py`, and
`get_imports` in `test_tools.py`. Not found: paths built in code (`os.path.join("images", x)`),
names with spaces, and Windows paths.
