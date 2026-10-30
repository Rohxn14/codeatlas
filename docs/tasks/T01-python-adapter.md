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
