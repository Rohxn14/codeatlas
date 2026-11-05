# T11f: HTTP linker review fixes

> **Reading note.** This brief is history. It is what a cloud session was told to build, kept so you can see what was asked; it is not an instruction for new work.
> - **Built in**: pull request #32.
> - **Read first**: `docs/explainers/http-linker.md`, for what was actually built and why.
> - **Code**: `src/codeatlas/indexer/linker/`, the HTTP parts of both deep adapters. **Tests**: `tests/indexer/linker/`.
> - **Then** read this brief and its review at the end: the gap between them is where the interesting questions are.
> - Reading order, glossary and how to study a module: `docs/README.md`.

**Wave**: 3 fixes (runs in parallel with T12f and T17f; no file overlap)
**Branch**: keep the one the cloud environment gives you
**Why**: T11's review (end of `docs/tasks/T11-http-linker.md`) found the fixture's CALLS_HTTP recall at 0.33 (2 of 6): the linker is right, but two adapters never emit the client calls. Linker problems also never reach the build report.

## Files you may edit

- `src/codeatlas/indexer/languages/python/http_calls.py`, `src/codeatlas/indexer/languages/typescript/http.py` (and the TypeScript adapter module that calls it, only if the base URL must travel through it)
- `src/codeatlas/indexer/pipeline/build.py`: only `_run_linkers`
- `src/codeatlas/indexer/linker/`
- tests for these (new files with unique names, or the existing linker tests), `docs/explainers/http-linker.md`

If carrying a base URL across files needs a contract change (for example a field on `RawHttpCall`), stop at that item, write a "Contract change request" section in the pull request, and finish the rest.

## Must fix

1. **TestClient calls are not emitted** (`python/http_calls.py`). `client = TestClient(app); client.post("/api/users")` gives no `RawHttpCall` (fixture `backend/tests/test_routes.py` lines 8, 11, 12). Treat any name assigned from `TestClient(...)` (and `httpx.Client(...)`, `requests.Session()`) in the same function or module as a client.
2. **axios instances created in another file** (`typescript/http.py`). `http.ts` exports `axios.create({ baseURL: "/api" })`; `client.ts:15` calls `http.post("/users")`, which should be `/api/users`. Record each module's exported axios instances with their base URL, and join it onto calls made through an imported instance. Then make `tests/indexer/linker/test_http_linker_build.py` assert all 6 fixture CALLS_HTTP pairs, and rewrite `test_http_linker.py:82` to parse `http.ts` and `client.ts` through the adapters instead of feeding an already-joined URL.
3. **Linker problems are dropped** (`pipeline/build.py` `_run_linkers`, about lines 229-236). Resolvers' `problems` reach `BuildResult.problems` (line 216); linkers' do not. Add `result.problems += [f"linker {name}: {p}" for p in getattr(linker, "problems", [])]`, and have `HttpLinker` add one summary line per unmatched reason (`"unmatched http calls: no_route=3"`). Test that both appear in `build_graph(...).problems`.

## Should fix (`src/codeatlas/indexer/linker/`)

4. `urls.py:42-48`: a placeholder host (`` `http://${API_HOST}:8000/api/users` ``, `f"http://{host}/api/users"`) is `external_host`; treat a placeholder host as local.
5. `urls.py:47`: `http://[::1]:8000/x` and `HTTP://LOCALHOST/x` are `external_host`. Use `urllib.parse.urlsplit(text).hostname` against `{"localhost", "127.0.0.1", "0.0.0.0", "testserver", "::1"}`.
6. `urls.py:49-50`: split the query and fragment after substituting placeholders, not before (`` `/api/users/${q ? 'a' : 'b'}` `` breaks today).
7. `http.py:285-293`: routes `GET /x` and `ANY /x` turn a literal `GET /x` into two 0.35 pattern edges. When a hit's method matches exactly, drop the `ANY` hits before deciding exact versus pattern.

## Later (do them if time allows)

8. `http.py:307-308`: a route segment mixing a parameter and text (`/files/{name}.json`) never matches; compile segments to regular expressions.
9. `urls.py:20`: `'/api/users/' + ids[0]` counts as dynamic; allow a subscript in a bare name.
10. `urls.py:16`: protocol-relative `//localhost/api/users` keeps `localhost` as a segment.

## Measure and done when

`python scripts/score_fixture.py` before and after in the pull request: CALLS_HTTP 6 of 6 (or the exact reason for any miss), HANDLES 3 of 3, no other kind changes. `pytest -q` and `ruff check .` pass; explainer updated. Pull request title: `T11f: HTTP linker review fixes`.
