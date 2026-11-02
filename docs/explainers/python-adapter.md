# Python adapter (deep tier)

## What

`PythonAdapter` turns one Python file into a `ParseResult`: the module node, a node for
every class, function, method and test, plus the raw facts the later stages connect
across files: imports, calls, server routes (FastAPI, Flask) and client HTTP calls
(requests, httpx). It reads one file at a time and never looks anything up elsewhere,
so every name stays exactly as written.

The code lives in `src/codeatlas/indexer/languages/python/`, one module per concern:

| Module | Produces |
| --- | --- |
| `adapter.py` | Parses once, calls the others, builds `Node`s and the `ParseResult` |
| `syntax.py` | Small tree-sitter helpers: text, spans, string literals, call arguments, callee parts |
| `definitions.py` | Classes and functions with qualnames, keys, signatures, decorators, docstrings; `Scopes` |
| `testing.py` | Marks pytest/unittest tests as `TEST` with a `test_id` |
| `imports.py` | `RawImport`s |
| `calls.py` | `RawCall`s |
| `routes.py` | `RawRoute`s |
| `http_calls.py` | `RawHttpCall`s |

## Why

- **tree-sitter, not Python's `ast`.** The brief asks for it: the same approach carries
  over to TypeScript and to the structural tier, and tree-sitter keeps going past a
  syntax error, so a half-edited file still yields its good parts plus an error.
  `ast.parse` gives up on the whole file.
- **One module per concern.** Each can be read and tested alone. They share one parse
  tree and the list of definitions, nothing else.
- **Same keys as the structural tier.** If the deep adapter fails to load, the registry
  falls back to the tags adapter. Repeated names (a property getter and setter are both
  `name`) therefore get T00's suffix, `#` plus a short hash of the signature, by calling
  T00's own `_duplicate_suffixes` rather than a copy of it. A test parses every sample
  with both tiers and checks the key sets are equal.
- **Signature stops at the colon, not at the body.** `def f():  # note` would otherwise
  carry the comment. The structural tier stops at the body, so the two differ only when
  a comment follows the colon of a *repeated* name; then the hash, and the key, differ.
- **Decorators, defaults and class bodies run in the enclosing scope.** Python evaluates
  them when the `def` or `class` statement runs, not when the function is called. So
  `@app.get("/x")` on a module-level function is a call made by the module, and
  `timeout = compute()` in a class body is a call by the module (a class is not a
  `CALLS` source in the contract). Rejected: attributing them to the decorated function,
  which would invent calls the function never makes.
- **Spans include decorators.** A diff that only edits `@router.get("/old")` changes the
  handler, so the impact engine should see it. The structural tier spans only the `def`;
  spans are not part of keys, so this does not affect matching.
- **Tests follow the runners' real rules**, so `test_id` is what pytest prints: prefix
  `test` (not only `test_`), classes `Test*` or any base whose last segment ends in
  `TestCase` (`unittest.TestCase`, `django.test.TestCase`, `IsolatedAsyncioTestCase`),
  and only in files named `test_*.py` or `*_test.py`.
- **Routes need evidence of a framework**, strongest first: what the router variable was
  created from in this file, then the decorator (`route` is Flask's, `api_route`
  FastAPI's), then which framework the file imports, then FastAPI. The last fallback
  keeps routes in a `views.py` that imports `app` from another file.
- **HTTP clients by variable, in the same function or at module level only.** Tracking
  `self.client` across methods would need type inference across a class; that belongs in
  the resolver if it is ever needed.

## How

1. `adapter.parse` builds the module node with T00's `module_node`, then parses with the
   tree-sitter Python grammar. Any exception gives just the module node plus
   `adapter failed: ...`, so a file is never dropped.
2. `collect_definitions` walks the tree in source order. Each `class_definition` and
   `function_definition` becomes a `PyDefinition` with its parent (the nearest enclosing
   definition), decorators (from the surrounding `decorated_definition`), bases or
   `is_async`, and its signature. Then `_assign_keys` builds qualnames parent first
   (`UserService.fetch.build`), adds T00's suffix to repeated names, and sets
   `owner_key` when the parent is a class.
3. `mark_tests` changes `FUNCTION` to `TEST` in test files and adds
   `test_id = path::Class::name`, built from the plain names.
4. `Scopes.caller_key(node)` walks up from any node. It returns a function's key only if
   it climbs into that function through the function's `body` field; climbing in through
   parameters or decorators skips it. No function: the module key.
5. `collect_imports`, `collect_calls`, `collect_routes` and `collect_http_calls` walk the
   same tree. Routes and HTTP calls first collect assignments in the file (router
   prefixes, client variables), then look at decorators or calls.
6. `syntax_errors` (T00's) lists ERROR and MISSING nodes into `errors`.

Worked example, `app.py`:

```python
import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api")

@router.get("/users/{user_id:int}")
async def get_user(user_id: int):
    async with httpx.AsyncClient() as client:
        return await client.get(f"/profiles/{user_id}")
```

- Nodes: module `app.py::`, then `app.py::get_user` (FUNCTION, `is_async: True`,
  decorators `['router.get("/users/{user_id:int}")']`, span from line 6).
- Imports: `RawImport("app.py::", "httpx")` and
  `RawImport("app.py::", "fastapi", (("APIRouter", None),))`.
- Calls: `APIRouter` and `router.get` (caller: the module), then
  `httpx.AsyncClient` and `client.get` (caller: `app.py::get_user`).
- Route: `router` was made by `APIRouter(prefix="/api")`, so
  `RawRoute("app.py::get_user", "GET", "/api/users/{user_id}", "fastapi", "router", 6)`;
  `{user_id:int}` is normalised to `{user_id}`.
- HTTP call: `client` comes from `httpx.AsyncClient()` in the same function, so
  `RawHttpCall("app.py::get_user", "httpx", "/profiles/{user_id}", "template", "GET", 9)`.

## Where

- **Registered** in `indexer/registry.py` under `DEEP_ADAPTERS["python"]`; the registry
  builds it with no arguments and falls back to the structural tier if it fails to load.
- **Reuses from T00** (`indexer/generic/adapter.py`): `module_node`, `syntax_errors`,
  and the private `_Definition` and `_duplicate_suffixes` for the key rule.
- **Contract types** (`models.py`): `Node`, `NodeKind` (`MODULE`, `CLASS`, `FUNCTION`,
  `TEST`), `Span`, `Tier.DEEP`, `RawImport`, `RawCall`, `RawRoute`, `RawHttpCall`,
  `ParseResult`, `make_key`, `make_node_id`. It satisfies `LanguageAdapter` from
  `indexer/adapter.py`.
- **Consumers**: the Python resolver (T06) turns imports and calls into `IMPORTS`,
  `CALLS`, `INHERITS` (from `attrs["bases"]`) and `TESTS` edges; the HTTP linker (T11)
  turns routes and HTTP calls into `ROUTE` nodes and `HANDLES`/`CALLS_HTTP` edges, using
  `router` to apply prefixes set in other files (`include_router`, `register_blueprint`).
