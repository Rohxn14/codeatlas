# T11: Cross-language HTTP linker

**Wave**: 3 (all of Wave 3 runs in parallel)
**Branch**: keep the one the cloud environment gives you

## Goal

Connect client HTTP calls to the server routes they hit, across languages: `fetch("/api/users/" + id)` in TypeScript reaches `@router.get("/users/{id}")` under `APIRouter(prefix="/api")` in Python. Then a change to a Python handler reaches the TypeScript code that calls it, which no single-language resolver can see. The fixture's 3 HANDLES and 6 CALLS_HTTP edges are the only labelled edges no task produces yet.

## Plan first, then build

Write `docs/plans/T11.md` (about one page) as your first commit, then keep going without waiting: the URL normalisation rules with examples from the fixture, the matching rule and its confidence levels, how router prefixes reach a route, your answers to "Decide in your plan", the tests, and what you expect to get wrong.

## Files you may create or edit

- `src/codeatlas/indexer/linker/` (new package), with a `HttpLinker` class satisfying the contract's `Linker` protocol
- `src/codeatlas/indexer/pipeline/plugins.py`: add exactly one entry, `"http": "codeatlas.indexer.linker:HttpLinker"`, to `LINKERS` (no other task edits this file in Wave 3)
- `tests/indexer/linker/` (test file names unique across `tests/`, such as `test_http_linker.py`), `tests/data/linker/`
- `docs/plans/T11.md`, `docs/explainers/http-linker.md`

Read `docs/explainers/pipeline.md`: `build_graph` runs every linker after the resolvers and writes the ROUTE nodes it returns. Measure with `python scripts/score_fixture.py`.

## What to build

**ROUTE nodes**, one per distinct (method, normalised path) a server defines, with the key from contract section 4: `{path of the handler's file}::route:{METHOD} {path_pattern}`, for example `backend/routes.py::route:GET /api/users/{id}`. `attrs`: `http_method`, `path_pattern`, `framework`.

**HANDLES** edges, Route → handler function (`RawRoute.handler_key`), resolution `STRUCTURAL`, 1.0. When the handler key is a module key (an inline Express arrow), create the route but no HANDLES edge, and count it in the linker's `problems`.

**CALLS_HTTP** edges, calling function → Route:

| Level | When | Confidence |
| --- | --- | --- |
| `ROUTE_EXACT` | a literal URL whose normalised path equals a route's path exactly, method matching | 0.9 |
| `ROUTE_PATTERN` | a template or concatenated URL whose parameters line up with a route's `{param}` segments, method matching | 0.7 |

**Normalising a client URL**: strip scheme, host and port (`http://localhost:8000/api/users` → `/api/users`) and any `{BASE}`/`${API}`-style host prefix the adapters keep in `url_text`; drop the query string and fragment; `${id}`, `{user_id}` and `" + id` become one parameter segment; collapse repeated slashes; compare paths case-sensitively. A client call with no method is `GET` (`fetch`'s default); an unknown method (options in a variable) matches any method at the pattern level only.

**Router prefixes**: the Python adapter already joins `APIRouter(prefix=...)` and blueprint prefixes in the same file. Express mounts (`app.use("/api", usersRouter)`) live in another file: find `use` calls with a literal prefix and a router name in the raw calls you are given if you can; otherwise say in the plan and the explainer that cross-file Express mounts are a v1 limitation.

**Clients**: TypeScript `fetch` and `axios` (including `axios.create` base URLs), Python `requests`, `httpx` and FastAPI's `TestClient` (the fixture's backend tests use it, and the labels count those calls).

Keep everything static: a URL built at run time from unknown parts stays unmatched and is counted.

## Decide in your plan

1. Several routes match one call at the pattern level (`/users/{id}` and `/users/{name}`): split the confidence, or keep the most specific?
2. A client and a server in different repositories never match here; should a call with a full host (`https://api.github.com/...`) become an EXTERNAL target instead of unmatched?
3. Trailing slashes: does `/api/users/` match `/api/users`?

## Tests

Snippets with exact expected nodes and edges: a literal fetch, a template fetch, an axios instance with a base URL, `requests` and `TestClient`, FastAPI with a router prefix, Flask with a blueprint, Express with params, an unknown method, a call matching nothing, two routes matching one pattern, a full-host URL. Plus the fixture through `build_graph`. No network.

## Measure and report

In the pull request: `python scripts/score_fixture.py` before and after (HANDLES and CALLS_HTTP precision and recall; every other kind must not change), and the linker on two real repositories with both a client and a server (choose them; one full-stack JavaScript, one with a Python backend), with routes found, calls matched, unmatched calls by reason.

## Done when

Tests pass on Linux and Windows CI; the plan is committed; the fixture's HANDLES and CALLS_HTTP are found; the explainer covers normalisation step by step with a fixture example, the two confidence levels, and what static linking cannot see.

## Review (Nov 3)

**Verdict**: merged (#28); "Done when" not fully met. HANDLES 3/3 at precision 1.0, other kinds unchanged, scope clean, contract followed. CALLS_HTTP recall 0.33 (2 of 6): the four misses are adapter gaps (FastAPI `TestClient` instances; an axios instance created in another file), not linker bugs. Linker problems never reach the build report. Fixes: `docs/tasks/T11f-linker-fixes.md`.

**Read these yourself**: `linker/urls.py` (normalisation, step by step), `linker/http.py` (matching and the two confidence levels).
