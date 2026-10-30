# The CodeAtlas contract

Two small files define every shape that modules pass to each other:

- `src/codeatlas/models.py`: the data (identifiers, enums, data classes)
- `src/codeatlas/indexer/adapter.py`: the interfaces (adapter, symbol index, resolver, linker)

You type both from this spec on Day 0. Cloud sessions read this file and never edit those two. A session that needs a change stops and writes a "Contract change request" in its pull request instead.

---

## 1. Why a contract comes first

Six sessions build the adapters, repository layer, store, LLM layer and fixtures at the same time, without seeing each other's code. They fit together only if they agree on what crosses the boundaries: what a node looks like, what an adapter returns, what a resolver receives. Writing those shapes down in two files with no logic makes the agreement explicit, reviewable in ten minutes, and testable (T00 adds a test that checks your files against this spec).

## 2. Rules for both files

| Rule | Why |
| --- | --- |
| Python 3.11+, standard library only: `dataclasses`, `enum`, `typing`, `collections.abc`, `pathlib` | The contract must import anywhere, with nothing installed |
| Data classes are `@dataclass(frozen=True, slots=True)` | Values never change after creation, so they are safe to cache and pass between stages |
| Enums subclass `StrEnum` | They store as readable strings in SQLite and JSON (`"calls"`, not `3`) |
| No logic except the three id helpers in section 4 | Logic belongs in modules that have tests |
| Paths are repo-relative with forward slashes on every OS: `backend/users.py` | You develop on Windows; the cloud VM is Linux; ids must match on both |
| Lines are 1-based and inclusive; columns are 0-based | Matches editors for lines and tree-sitter for columns |
| Fields with a mutable default use `field(default_factory=dict)` | A shared mutable default is a classic Python bug |

A frozen data class that holds a `dict` can still be created and read; it just cannot be hashed. Never put nodes in a set or use them as dict keys; use their `id`.

## 3. Languages and tiers

`language` is a plain `str`: the tree-sitter grammar name, such as `"python"`, `"typescript"`, `"tsx"`, `"javascript"`, `"go"`, `"java"`. Plain strings keep the structural tier open to any grammar without editing an enum.

CodeAtlas is repository-first: every repository gets a **repository layer** (packages, manifests, test conventions, change history) whatever its languages, and each file additionally gets a **tier** saying how deeply its language is understood.

Define one constant:

| Name | Value |
| --- | --- |
| `DEEP_LANGUAGES` | `frozenset({"python", "typescript", "tsx", "javascript"})` |

## 4. Identifiers

| Name | Format | Example | Used for |
| --- | --- | --- | --- |
| snapshot id | `{repo}@{sha[:12]}` | `polyglot_app@3f2a9c1e5b7d` | one indexed commit |
| node key | `{path}::{qualname}` | `backend/users.py::UserService.save` | the same symbol across snapshots |
| module key | `{path}::` (empty qualname) | `backend/users.py::` | the file itself |
| package key | `{manifest_path}::package:{name}` | `frontend/package.json::package:web-app` | a package declared by a manifest; the prefix keeps it apart from the manifest file's own module node |
| node id | `{snapshot_id}/{key}` | `polyglot_app@3f2a9c1e5b7d/backend/users.py::UserService.save` | a symbol in one snapshot |
| citation | `{repo}@{sha[:12]}:{path}:{line}` | `polyglot_app@3f2a9c1e5b7d:backend/users.py:42` | answers the agent gives |

**Qualname**: the dotted path inside the file. A method is `Class.method`; a nested function is `outer.inner`. A TypeScript test is its `describe` and `it`/`test` names joined with ` > `, for example `UserApi > fetches a user`.

**Why both key and id**: the key survives a new commit, so the impact engine and the evaluation compare symbols across snapshots by key. The id is unique in the store.

Three helper functions, the only logic in `models.py`:

| Function | Returns |
| --- | --- |
| `make_snapshot_id(repo: str, sha: str) -> str` | `f"{repo}@{sha[:12]}"` |
| `make_key(path: str, qualname: str) -> str` | `f"{path}::{qualname}"` |
| `make_node_id(snapshot_id: str, key: str) -> str` | `f"{snapshot_id}/{key}"` |

## 5. Enums

**`Tier`**: how deeply a language is understood.

| Member | Value | Meaning |
| --- | --- | --- |
| `DEEP` | `"deep"` | Hand-written adapter and resolver |
| `STRUCTURAL` | `"structural"` | Tags query for definitions and calls, plus, where written, an imports query and a resolution profile for import-scoped calls |
| `TEXT` | `"text"` | File node only, no symbols (config, SQL, docs) |

**`NodeKind`**

| Member | Value | Meaning |
| --- | --- | --- |
| `PACKAGE` | `"package"` | A workspace package, module or crate declared by a manifest |
| `MODULE` | `"module"` | One file, in any language |
| `CLASS` | `"class"` | A class or struct |
| `INTERFACE` | `"interface"` | A TypeScript, Java or Go interface |
| `FUNCTION` | `"function"` | A function or method (methods have `owner_key` set) |
| `TEST` | `"test"` | A test function or test case |
| `ROUTE` | `"route"` | An HTTP endpoint a server defines (created by the linker) |
| `EXTERNAL` | `"external"` | A symbol imported from outside the repo |

**`EdgeKind`**

| Member | Value | From → to |
| --- | --- | --- |
| `CONTAINS` | `"contains"` | Package → Module; Module → Class, Interface or Function; Class → method |
| `DEPENDS_ON` | `"depends_on"` | Package → Package (a manifest dependency inside the same repository) |
| `IMPORTS` | `"imports"` | Module → Module, symbol or External |
| `CALLS` | `"calls"` | Function or Test → Function or External |
| `INHERITS` | `"inherits"` | Class → Class or Interface |
| `TESTS` | `"tests"` | Test → Function, or test Module → Module (by naming convention) |
| `HANDLES` | `"handles"` | Route → Function |
| `CALLS_HTTP` | `"calls_http"` | Function → Route |
| `CO_CHANGES` | `"co_changes"` | Module → Module; directional, so a pair gets two edges |

**`Resolution`**: how an edge was established. The confidence on each edge comes from this, as set out in the project plan.

| Member | Value | Typical confidence |
| --- | --- | --- |
| `STRUCTURAL` | `"structural"` | 1.0 (containment, a resolved import, a declared base class) |
| `DIRECT` | `"direct"` | 1.0 |
| `SELF_METHOD` | `"self_method"` | 0.9 |
| `ROUTE_EXACT` | `"route_exact"` | 0.9 |
| `ROUTE_PATTERN` | `"route_pattern"` | 0.7 |
| `IMPORT_SCOPED` | `"import_scoped"` | 1 ÷ candidates found in the caller's file and the files it imports |
| `NAME_GUESS` | `"name_guess"` | 1 ÷ candidates anywhere in the repo, same language, capped at 0.3 |
| `CONVENTION` | `"convention"` | 0.8 (a test file matched to a source file by naming) |
| `HISTORY` | `"history"` | Commits changing both ÷ commits changing the source file |

Unresolved calls never become edges; they stay as raw calls, so the evaluation can count them.

## 6. Data classes

### `Span`

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `start_line` | `int` | | First line, 1-based |
| `end_line` | `int` | | Last line, inclusive |
| `start_col` | `int` | `0` | 0-based column |
| `end_col` | `int` | `0` | 0-based column |

### `FileRecord`: one file seen by discovery

| Field | Type | Meaning |
| --- | --- | --- |
| `path` | `str` | Repo-relative, forward slashes |
| `language` | `str` | Grammar name, or `"text"` |
| `tier` | `Tier` | |
| `sha256` | `str` | Content hash, drives incremental re-index |
| `size_bytes` | `int` | |

### `Snapshot`: one indexed commit

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `id` | `str` | | From `make_snapshot_id` |
| `repo` | `str` | | Short repo name |
| `commit_sha` | `str` | | Full SHA |
| `indexed_at` | `str` | | ISO 8601 UTC, e.g. `2026-10-30T09:15:00Z` |
| `indexer_version` | `str` | | Package version, so old indexes can be detected |
| `source` | `str` | | Where it came from: a local path or a GitHub URL |
| `limits_hit` | `tuple[str, ...]` | `()` | Limits reached while indexing, e.g. `("max_files",)`; empty means the index is complete |

### `Node`

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `id` | `str` | | From `make_node_id` |
| `key` | `str` | | From `make_key` |
| `snapshot_id` | `str` | | |
| `kind` | `NodeKind` | | |
| `language` | `str` | | |
| `name` | `str` | | Short name: `save` |
| `qualname` | `str` | | `UserService.save`; empty for modules |
| `path` | `str` | | |
| `span` | `Span` | | |
| `signature` | `str \| None` | `None` | As written: `def save(self, user: User) -> None` |
| `docstring` | `str \| None` | `None` | Docstring or leading doc comment |
| `owner_key` | `str \| None` | `None` | Key of the class for a method |
| `attrs` | `dict[str, object]` | `{}` | Kind-specific extras, listed below |

Common `attrs` keys: `decorators` (list of str), `is_async` (bool), `bases` (list of str, as written), `exported` (bool, TS), `test_id` (the runner's id), `http_method`, `path_pattern`, `framework` (routes), `package_key` (modules: the package that contains the file), `ecosystem`, `manifest`, `version` (packages: `npm`, `pypi`, `go`, `cargo`, `maven`, `gradle`, `nuget`, `composer`, ...).

### `Edge`

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `src_id` | `str` | | |
| `dst_id` | `str` | | |
| `kind` | `EdgeKind` | | |
| `confidence` | `float` | | In (0, 1] |
| `resolution` | `Resolution` | | |
| `line` | `int \| None` | `None` | Line in the source file where the edge comes from, e.g. the call line |
| `attrs` | `dict[str, object]` | `{}` | Extras, e.g. `candidates` for a name guess; `support` (commits changing both) and `source_commits` for co-change |

### Raw items: what adapters emit and resolvers consume

These exist only inside one indexing run. Adapters cannot resolve names across files, so they record what they saw, as written.

**`RawImport`**

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `module_key` | `str` | | Key of the importing file |
| `target` | `str` | | As written: `..services.users`, `./api`, `react` |
| `names` | `tuple[tuple[str, str \| None], ...]` | `()` | Imported names with aliases: `(("save", None), ("User", "U"))`; empty for whole-module imports; a TS default import is `("default", "X")` |
| `alias` | `str \| None` | `None` | Alias for a whole-module import: `import numpy as np` |
| `level` | `int` | `0` | Python relative-import dots; 0 elsewhere |
| `is_reexport` | `bool` | `False` | TS `export ... from` |
| `line` | `int` | `0` | |

**`RawCall`**

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `caller_key` | `str` | | Key of the enclosing function, or the module key at top level |
| `callee_text` | `str` | | As written: `self.repo.save`, `fetchUser`, `obj.save` |
| `name` | `str` | | Last segment: `save` |
| `receiver` | `str \| None` | `None` | Everything before the last segment: `self.repo` |
| `line` | `int` | `0` | |

**`RawRoute`**: a server endpoint as written

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `handler_key` | `str` | | Key of the function that serves it |
| `method` | `str` | | `GET`, `POST`, ... or `ANY` |
| `path_pattern` | `str` | | Normalised to `{param}` style: `/api/users/{id}` |
| `framework` | `str` | | `fastapi`, `flask`, `express` |
| `router` | `str \| None` | `None` | Router variable name, so the linker can apply prefixes set elsewhere |
| `line` | `int` | `0` | |

**`RawHttpCall`**: a client request as written

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `caller_key` | `str` | | |
| `client` | `str` | | `fetch`, `axios`, `requests`, `httpx` |
| `url_text` | `str` | | Literal or template as written |
| `url_kind` | `str` | | `literal`, `template` or `dynamic` |
| `method` | `str \| None` | `None` | Known HTTP method, if any |
| `line` | `int` | `0` | |

### `ParseResult`: everything an adapter learned from one file

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `path` | `str` | | |
| `language` | `str` | | |
| `tier` | `Tier` | | |
| `nodes` | `tuple[Node, ...]` | | All nodes, module node first |
| `imports` | `tuple[RawImport, ...]` | `()` | |
| `calls` | `tuple[RawCall, ...]` | `()` | |
| `routes` | `tuple[RawRoute, ...]` | `()` | |
| `http_calls` | `tuple[RawHttpCall, ...]` | `()` | |
| `errors` | `tuple[str, ...]` | `()` | Parse problems; never raise for bad syntax |

Tuples instead of lists keep the result immutable, like the frozen classes.

## 7. Interfaces (`indexer/adapter.py`)

Use `typing.Protocol`, so any class with matching attributes and methods fits, without inheritance. Mark them `@runtime_checkable` so tests can assert `isinstance(x, LanguageAdapter)`.

**`LanguageAdapter`**: turns one file into a `ParseResult`

| Member | Signature | Rule |
| --- | --- | --- |
| `language` | `str` | Primary grammar name |
| `tier` | `Tier` | |
| `extensions` | `tuple[str, ...]` | e.g. `(".py",)` |
| `parse` | `(self, path: str, source: bytes, snapshot_id: str) -> ParseResult` | Pure: no file or network access; never raises on bad syntax |

**`SymbolIndex`**: read-only lookups resolvers and linkers need. The store implements it (T03); tests use a small in-memory version.

| Method | Signature |
| --- | --- |
| `by_key` | `(self, key: str) -> Node \| None` |
| `by_name` | `(self, name: str, language: str \| None = None) -> list[Node]` |
| `module_for_path` | `(self, path: str) -> Node \| None` |
| `members` | `(self, class_key: str) -> list[Node]` |
| `files` | `(self) -> list[FileRecord]` |

**`RepoAnalyzer`**: whole-repository analysis that needs no parser (the repository layer)

| Member | Signature | Rule |
| --- | --- | --- |
| `name` | `str` | e.g. `"manifests"`, `"cochange"`, `"test_conventions"` |
| `analyze` | `(self, repo_root: Path, files: Sequence[FileRecord], snapshot_id: str) -> tuple[list[Node], list[Edge]]` | May read files and run read-only `git` commands; never runs build tools, package managers or repository code |

**`Resolver`**: turns one language family's raw items into edges

| Member | Signature | Rule |
| --- | --- | --- |
| `languages` | `frozenset[str]` | e.g. `{"typescript", "tsx", "javascript"}`; the structural resolver lists every language with a resolution profile |
| `resolve` | `(self, results: Sequence[ParseResult], index: SymbolIndex) -> list[Edge]` | Produces IMPORTS, CALLS, INHERITS and TESTS edges for its languages. CONTAINS edges come from the pipeline, for every tier. |

**`Linker`**: connects things across files and languages

| Member | Signature | Rule |
| --- | --- | --- |
| `name` | `str` | e.g. `"http"` |
| `link` | `(self, results: Sequence[ParseResult], index: SymbolIndex, snapshot_id: str) -> tuple[list[Node], list[Edge]]` | May create nodes (ROUTE) and edges (HANDLES, CALLS_HTTP) |

## 8. Graph export for the scorer

The graph-accuracy scorer (T05) compares graphs by **key**, so it works across snapshots and against SCIP ground truth. The export is one JSON object:

```json
{
  "snapshot": {"id": "...", "repo": "...", "commit_sha": "...", "indexed_at": "...", "indexer_version": "...", "source": "...", "limits_hit": []},
  "nodes": [{"key": "...", "kind": "function", "language": "python", "path": "...", "span": {"start_line": 1, "end_line": 9}}],
  "edges": [{"src_key": "...", "dst_key": "...", "kind": "calls", "confidence": 0.9, "resolution": "self_method", "line": 12}]
}
```

No helper for this lives in the contract; T03 writes the exporter and T05 the reader, both following this shape.

## 9. When you finish typing

1. Run `python -c "import codeatlas.models, codeatlas.indexer.adapter"` (after T00 adds the package files, or with empty `__init__.py` files you create).
2. Read your file against sections 4 to 7 once more; T00's contract test will flag any mismatch.
3. Commit with the message `contract: models and adapter interfaces`.
