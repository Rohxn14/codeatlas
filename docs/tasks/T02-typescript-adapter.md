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
