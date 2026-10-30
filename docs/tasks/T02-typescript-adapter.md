# T02: TypeScript and JavaScript adapter (deep tier)

**Wave**: 1 (parallel with T01, T03 to T05)
**Branch**: `task/T02-typescript-adapter`

## Goal

One deep `LanguageAdapter` family covering `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs` and `.cjs`, extracting what the TS resolver (T07) and the HTTP linker (T11) need, one file at a time.

## Files you may create or edit

- `src/codeatlas/indexer/languages/typescript/` (any modules inside it)
- Registration in `src/codeatlas/indexer/registry.py`: add entries for `typescript`, `tsx` and `javascript` only
- `tests/indexer/typescript/`, `tests/data/typescript/`
- `docs/explainers/typescript-adapter.md`

## What to extract

| Item | Details |
| --- | --- |
| Module node | Always first |
| Classes | Name, span, `extends` and `implements` in `attrs["bases"]`, decorators, leading JSDoc as docstring, `attrs["exported"]` |
| Interfaces and type aliases | Interfaces become INTERFACE nodes; type aliases are skipped in v1 |
| Functions | Function declarations, `const f = () => ...` and `const f = function ...` at module level, class methods (with `owner_key`), object-literal methods on exported objects; signature text as written; `is_async`; `attrs["exported"]` |
| React components | No special kind: a component is a FUNCTION. Calls also include JSX elements whose tag starts with a capital letter (`<UserCard />` is a call to `UserCard`) |
| Tests | Files matching `*.test.*`, `*.spec.*` or under `__tests__/`. Each `it(...)`/`test(...)` call with a string name becomes a TEST node whose qualname is the enclosing `describe` names and its own joined with ` > `; `attrs["test_id"]` is the same string; calls inside the test body get that test's key as `caller_key` |
| Imports | `import X from`, `import {a as b} from`, `import * as ns from`, side-effect `import "x"`, `export {a} from`, `export * from` (`is_reexport=True`), `require("x")` assigned to a name, and dynamic `import("x")` with a literal; a default import is the name `("default", "X")` |
| Calls | `callee_text` as written, `name`, `receiver`; `caller_key` = innermost enclosing named function, method or test; anonymous callbacks belong to their enclosing named function |
| Routes | Express: `app.get("/x", handler)`, `router.post("/x", ...)`, `app.route("/x").get(...)`. Normalise `:id` to `{id}`. `handler_key` is the named function when the handler is an identifier; for an inline arrow handler, use the module key in v1 and note the limitation in the explainer |
| HTTP calls | `fetch(url, {method})`, `axios.get/post/...(url)`, `axios({url, method})`, and instances from `axios.create({baseURL})` in the same file (store the base URL in the call's `url_text` prefix). Template literals are `template`; identifiers are `dynamic` |

## Design notes

- Use the `typescript` grammar for `.ts`, the `tsx` grammar for `.tsx`, and the `javascript` grammar for JS files. Share extraction code where the node types match; isolate differences.
- Keep extraction per concern in separate small modules, as in T01, so the two adapters read the same way.

## Tests

Snippets in `tests/data/typescript/` with exact expected outputs for: every import and export form above, classes implementing interfaces, arrow-function exports, a React component rendering two child components, Jest/Vitest tests with nested `describe` blocks, Express routes with params, fetch and axios calls (literal, template, base URL instance), and a file with a syntax error.

## Done when

All tests pass; `codeatlas scan` on `tests/data/typescript` reports the deep tier for all three grammars; explainer written.

## Notes from T00 (read before starting)

T00 is merged, so build on what exists:

- **Registration**: the registry imports deep adapters from the `DEEP_ADAPTERS` dictionary in `src/codeatlas/indexer/registry.py`, as `"<language>": "module.path:ClassName"`. Each class is constructed with no arguments. An adapter has a single `language`, so provide three small classes sharing one implementation, for `typescript`, `tsx` and `javascript`, and add exactly three lines to `DEEP_ADAPTERS`. T01 edits the same dictionary in parallel, so change nothing else in that file.
- **Shared helpers**: reuse `module_node` (the module node every adapter emits first) and `syntax_errors` from `src/codeatlas/indexer/generic/adapter.py` instead of writing your own.
- **Keys for repeated names** must follow T00's rule, so a symbol gets the same key whichever tier parses it: `#` plus a short hash of the signature text, with an ordinal only when two signatures are identical. Import T00's helper for this from `generic/adapter.py` even though it is private, and do not edit that file; mention the import in the pull request.
- **Tree-sitter positions**: read rows as `node.start_point[0]`, not `.row`; T00 found `.row` breaks on some tree-sitter versions.
- **Sample files**: pytest does not collect anything under `tests/data/` (`collect_ignore` in `tests/conftest.py`), so snippet files named like tests are safe there.

## Review of PR #8 (Oct 30)

**Verdict**: merge after fixes. **Fixes**: issue #15. Paste it into the T02 session. Merge PR #6 (T01) first; then this PR conflicts in `registry.py`, and part 0 of the issue tells the session how to resolve it (keep all four `DEEP_ADAPTERS` lines).

**What the PR does**: one deep-tier extractor shared by three small classes (`TypeScriptAdapter`, `TsxAdapter`, `JavaScriptAdapter`), one module per concern on shared helpers in `syntax.py`. It produces classes, interfaces, functions and methods, Jest/Vitest TEST nodes named `A > b`, every import form, calls (including `new` and JSX components), Express routes, and fetch/axios calls. The structure and tests are good; the main defect is that 20% of literal `require()` calls in real code disappear.

| Check | Result | Evidence |
| --- | --- | --- |
| Scope | WARN | Also edits `tests/test_registry.py` (`Registry()` to `Registry(deep={})`), disclosed and justified |
| Contract untouched | PASS | No diff in `models.py`, `indexer/adapter.py` or `pyproject.toml` |
| Tests | PASS | 172 passed; 28 for the adapter |
| Lint | PASS | `ruff check .` clean |
| Mutation spot-check | WARN | 4 of 5 caught; deleting the `startswith("/")` route check survives |
| Explainer | PASS | What, Why, How, Where, a worked example on `client.ts`, a limitations list |
| Brief coverage | PASS | `scan tests/data/typescript` shows all three grammars as deep |
| Safety | PASS | No subprocess, exec, eval or importlib |
| Silent gaps | WARN | Unbound `require("x")` dropped (must fix 1); named class expressions skipped (should fix 3) |
| Real code | PASS | 1,603 files (18 MB) from Node's global packages: 0 exceptions, 31 s, 28,072 nodes, 159,613 calls, no duplicate keys |

**Must fix** (issue #15, parts 1 to 3)
1. `imports.py:104`, `calls.py:21`: a literal `require("x")` or `import("x")` not bound by `const x =` becomes neither an import nor a call: `require("dotenv").config()`, `app.use(require("./routes"))`, `module.exports = require("./x")`. In real code that was 1,051 of 5,186 literal requires.
2. `symbols.py:423`: a strict `.decode()` turns one non-UTF-8 byte into a failure of the whole file.
3. `routes.py:56`: any `x.get("/path", <anything>)` is a route, so `api.get("/users", { params })` on an imported axios client becomes a server route and its HTTP call is lost.

**Should fix** (issue #15, parts 3 to 5)
1. The `startswith("/")` check has no test, and the explainer credits the wrong rule for rejecting `app.get("title")`.
2. `http.py:121`: `"https://x.io/api/"` + `"/users"` gives `//users`.
3. `symbols.py:163`: `module.exports = class Repo extends Base {}` and `const Svc = class {}` produce no CLASS node.

**Your decisions** (write your answer next to each)

| # | Question | Recommendation |
| --- | --- | --- |
| 1 | Arguments shortened to `(...)` in chained callee text | Accept; T07 must expect this format |
| 2 | Literal `require`/`import()` is an import, not a call | Accept, once must fix 1 makes every one an import |
| 3 | `new Foo()` is a call to `Foo` | Accept; matches Python |
| 4 | `url_text` without quotes, `${id}` kept, dynamic URLs as `"/api" + ...` | Accept; T11 treats `${...}` as a parameter |
| 5 | `fetch` with no method is GET; options in a variable give `None` | Accept |
| 6 | Methods copy their class's `exported` | Accept |
| 7 | Spans start at `const`, not `export` | Accept |
| 8 | `test_id` without the `#hash` | Accept: matches `jest -t` |
| 9 | Anonymous default exports named `default` | Accept: matches the `("default", X)` import name |
| 10 | Mocha/Jasmine spellings | Accept |
| 11 | CommonJS exports count as `exported` | Accept |
| 12 | A private method's key is `a.ts::A.#secret`, which looks like the `#hash` suffix | Add one line to the contract: `#` right after `.` is part of the name (D-16) |
| 13 | Every `recv.get("/p", h)` is labelled `express` (also Fastify, Hono, koa-router) | Keep for v1; decide when T11 is designed |
| 14 | When an extractor raises, the file keeps only its module node | Later: a per-file fallback to the structural tier |

**Try it yourself** (PowerShell, after `gh pr checkout 8`)

```powershell
codeatlas scan tests/data/typescript     # expect census rows: typescript deep 6, javascript deep 2, tsx deep 1
python -c "from codeatlas.indexer.languages.typescript.adapter import TypeScriptAdapter as A; r = A().parse('users.test.ts', open('tests/data/typescript/users.test.ts', 'rb').read(), 's'); print([n.qualname for n in r.nodes[1:]])"
```

The second command prints the nested test names: `['UserApi > fetches a user', 'UserApi > errors > rejects a missing user', 'UserApi > errors > retries', 'top level']`.

**Read these yourself**
- `src/codeatlas/indexer/languages/typescript/symbols.py:118-136` (`_assign_qualnames`): how T00's hash helper is reused, and why `test_id` and the key differ.
- `src/codeatlas/indexer/languages/typescript/imports.py:25-35, 84-104` with `calls.py:21`: the "import, not a call" decision and exactly where must fix 1 comes from.
- `src/codeatlas/indexer/languages/typescript/routes.py:36-65`: what counts as a route, and the heuristic behind must fix 3.
