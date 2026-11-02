# T01: Python adapter (deep tier)

**Wave**: 1 (parallel with T02 to T05)
**Branch**: `task/T01-python-adapter`

## Goal

A deep `LanguageAdapter` for Python that extracts everything the Python resolver (T06) and the HTTP linker (T11) will need, from one file at a time, with no cross-file lookups.

## Files you may create or edit

- `src/codeatlas/indexer/languages/python/` (any modules inside it)
- Registration of the adapter in `src/codeatlas/indexer/registry.py`: add one entry only
- `tests/indexer/python/`, `tests/data/python/`
- `docs/explainers/python-adapter.md`

## What to extract

| Item | Details |
| --- | --- |
| Module node | Always first; `qualname` empty |
| Classes | Name, span, bases as written in `attrs["bases"]`, decorators, docstring |
| Functions and methods | Signature text as written, decorators, `is_async`, docstring, `owner_key` for methods; nested functions get qualname `outer.inner` |
| Tests | pytest conventions: files `test_*.py` or `*_test.py`; functions named `test_*`; methods named `test_*` in classes named `Test*`; also methods of classes whose bases include `TestCase` or `unittest.TestCase`. Kind TEST, `attrs["test_id"]` in pytest node-id form `path::Class::test_name` |
| Imports | `import a.b`, `import a.b as c`, `from . import x`, `from ..pkg.mod import a as b, c`, `from x import *` (names `(("*", None),)`), with `level` for relative imports |
| Calls | Every call expression: `callee_text` as written, `name` = last segment, `receiver` = the rest, `caller_key` = innermost enclosing function or method (module key at top level), including calls inside decorators and default arguments |
| Routes | FastAPI: `@app.get("/x")`, `@router.post("/x")` and so on, plus `@app.api_route(path, methods=[...])`; Flask: `@app.route("/x", methods=[...])`, `@bp.get("/x")`. Normalise `<int:id>` and `{id}` to `{id}`. Set `router` to the decorator's object name (`app`, `router`, `bp`). If the same file creates `APIRouter(prefix="/api")` or `Blueprint(..., url_prefix="/api")` and assigns it to that name, apply the prefix |
| HTTP calls | `requests.get/post/...`, `requests.request(method, url)`, `httpx.get/...`, and `client.get/...` where `client` was created from `httpx.Client(...)` or `requests.Session()` in the same function or module. `url_kind` is `literal` for a plain string, `template` for an f-string or `.format`, `dynamic` otherwise |

## Design notes

- Use the Python tree-sitter grammar, not Python's `ast` module: the same approach must carry over to other languages, and tree-sitter tolerates syntax errors.
- Keep extraction per concern in separate small modules (definitions, imports, calls, routes, tests) so the owner can read each in isolation.
- Use spans from tree-sitter (1-based lines). Signatures are the source text from `def` up to the colon.

## Tests

Put realistic snippets in `tests/data/python/` and assert exact outputs for:

- nested classes and functions, decorators, async functions, properties, static and class methods
- every import form listed above
- calls with receivers (`self.repo.save()`), chained calls (`a().b()`), calls inside comprehensions and lambdas (caller is the enclosing function)
- FastAPI and Flask routes, including a router with a prefix in the same file
- requests and httpx calls with literal, f-string and variable URLs
- pytest and unittest test detection
- a file with a syntax error: partial result plus an error message

## Done when

All tests pass; `codeatlas scan` on `tests/data/python` reports deep-tier Python with the expected counts; explainer written.

## Notes from T00 (read before starting)

T00 is merged, so build on what exists:

- **Registration**: the registry imports deep adapters from the `DEEP_ADAPTERS` dictionary in `src/codeatlas/indexer/registry.py`, as `"<language>": "module.path:ClassName"`. Each class is constructed with no arguments. Add exactly one line: `"python": "codeatlas.indexer.languages.python.adapter:PythonAdapter"`. T02 edits the same dictionary in parallel, so change nothing else in that file.
- **Shared helpers**: reuse `module_node` (the module node every adapter emits first) and `syntax_errors` from `src/codeatlas/indexer/generic/adapter.py` instead of writing your own.
- **Keys for repeated names** must follow T00's rule, so a symbol gets the same key whichever tier parses it: `#` plus a short hash of the signature text, with an ordinal only when two signatures are identical. Import T00's helper for this from `generic/adapter.py` even though it is private, and do not edit that file; mention the import in the pull request.
- **Tree-sitter positions**: read rows as `node.start_point[0]`, not `.row`; T00 found `.row` breaks on some tree-sitter versions.
- **Sample files**: pytest does not collect anything under `tests/data/` (`collect_ignore` in `tests/conftest.py`), so snippet files named like tests are safe there.

## Review of PR #6 (Oct 30)

**Verdict**: merge after fixes. **Fixes**: issue #13. Paste it into the T01 session, wait for CI, then merge. Merge this before PR #8 (T02); both add lines to `DEEP_ADAPTERS`, and T02 resolves the conflict.

**What the PR does**: `PythonAdapter`, a deep-tier adapter on tree-sitter, with one module per concern (definitions, tests, imports, calls, routes, HTTP calls). Every item in the brief is extracted and tested with exact assertions, and keys for repeated names reuse T00's own helper. It registers with one `DEEP_ADAPTERS` line and updates five T00 tests that assumed Python was structural (disclosed in the PR).

| Check | Result | Evidence |
| --- | --- | --- |
| Scope | WARN | Also edits `tests/test_discover.py` and `tests/test_registry.py`: forced by the registration, minimal, disclosed |
| Contract untouched | PASS | No diff in `models.py` or `indexer/adapter.py` |
| Tests | PASS | 178 passed; 34 for the adapter |
| Lint | PASS | `ruff check .` clean |
| Mutation spot-check | PASS | 3 of 3 caught: the body check in `Scopes.caller_key`, the router prefix, the relative-import level |
| Explainer | PASS | What, Why, How, Where; the worked example's output matches when run |
| Brief coverage | PASS | `scan tests/data/python` reports `python deep`: 9 modules, 10 classes, 41 functions and tests, 50 calls, 1 syntax error |
| Safety | PASS | Parses bytes only; no subprocess, exec, eval or import of repository code |
| Silent gaps | WARN | A route whose path is not a literal is dropped without a record (accepted for now, question 9) |
| Real code | PASS | No exceptions on 4,646 site-packages files (67 s): networkx 583 files in 5.5 s, 54,227 calls; no duplicate keys |

**Must fix** (issue #13, part 1)
1. `routes.py:87-98`: `patch` is an HTTP verb, so `@mock.patch("os.getcwd")` in a test file becomes a `PATCH` route through the FastAPI fallback. Common in real test suites; it would feed false routes to the linker (T11). Fix: a route path must be `""` or start with `/`.

**Found while cross-checking with T05** (issue #13, part 2, decision D-11 in `docs/day2.md`)
2. The fixture labels count `@logged` above `create_user` as a call from `create_user` to `logged`. This adapter records nothing for a bare `@logged` and credits `@deco(1)` to the module, so that edge can never exist, and the impact engine would miss that changing a decorator changes every function it wraps. The issue asks the session to credit function decorators to the decorated function.

**Should fix** (issue #13, parts 3 and 4)
3. `definitions.py:149`: CRLF docstrings keep `\r` on Python 3.11 and 3.12, so the same file gives a different docstring on Windows than on Linux.
4. The explainer understates when deep and structural keys differ for repeated names: any comment between the colon and the body changes T00's signature text (59 of 4,646 files). The cause is in T00's `_signature`; see "Your small fix" in `docs/day2.md`.

**Your decisions** (write your answer next to each)

| # | Question | Recommendation |
| --- | --- | --- |
| 1 | Calls in decorators, defaults and class bodies go to the scope around the definition | Accept for defaults and class bodies; reverse it for function decorators (D-11) |
| 2 | A test is any `test*` name, plus classes whose bases end in `TestCase` | Accept: pytest's defaults. A subclass of a local `BaseTest(TestCase)` is left to T06 |
| 3 | Spans include decorators | Accept: editing a decorator should count as editing the function |
| 4 | No framework evidence means `fastapi` | Accept only with must fix 1 |
| 5 | Non-literal `methods=` gives `ANY`; `route` without `methods` gives `GET` | Accept |
| 6 | `url_text` is the text inside the quotes | Accept; the linker brief (T11) must strip host prefixes such as `{BASE}` |
| 7 | Extras: module docstring, `AsyncClient`, `with ... as`, `__future__` | Accept |
| 8 | `callee_text` has line breaks removed | Accept |
| 9 | Non-literal route paths dropped without a record | Accept for now; revisit in T11 |

**Try it yourself** (PowerShell, after `gh pr checkout 6`)

```powershell
codeatlas scan tests/data/python                 # expect a row: python deep 9 10 0 41 50 1
python -m pytest -q tests/indexer/python         # expect: 34 passed
python -c "from pathlib import Path; from codeatlas.indexer.languages.python.adapter import PythonAdapter as A; r = A().parse('app/fastapi_routes.py', Path('tests/data/python/app/fastapi_routes.py').read_bytes(), 's@0'); print(*[(x.method, x.path_pattern) for x in r.routes], sep='\n')"
```

The last command prints 6 routes, from `('GET', '/health')` to `('GET', '/items/{item_id}')`, with the router's `/api/users` prefix applied in between.

**Read these yourself**
- `src/codeatlas/indexer/languages/python/definitions.py:152-174` (`Scopes.caller_key`): this one decision sets the caller of every call and HTTP call, and part 2 of the issue changes it.
- `src/codeatlas/indexer/languages/python/routes.py:73-103`: how the framework is chosen from evidence, and where the fake-route bug comes from.
- `src/codeatlas/indexer/languages/python/definitions.py:125-136`: how the adapter borrows T00's private key helper, its only coupling to T00's code.
