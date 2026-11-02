# The TypeScript and JavaScript adapter (deep tier)

Modules: `src/codeatlas/indexer/languages/typescript/` (`adapter.py`, `syntax.py`,
`symbols.py`, `imports.py`, `calls.py`, `routes.py`, `http.py`), registered in
`src/codeatlas/indexer/registry.py`.

## What

It reads one `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs` or `.cjs` file (plus `.mts` and `.cts`)
and returns a `ParseResult` with:

- **nodes**: the module first, then classes, interfaces, functions, methods and tests, each
  with its span, signature, JSDoc, and `attrs` (`bases`, `decorators`, `is_async`,
  `exported`, `test_id`);
- **imports** exactly as written: ES imports, re-exports, `require` and dynamic `import()`;
- **calls**, including `new Foo()` and JSX components such as `<UserCard />`, each tied to
  the named function, method or test it happens in;
- **routes** declared with Express (`app.get("/users/:id", handler)`);
- **HTTP calls** made with `fetch` or `axios`, including axios clients built with
  `axios.create({ baseURL })` in the same file.

Three tiny classes, `TypeScriptAdapter`, `TsxAdapter` and `JavaScriptAdapter`, share one
implementation and differ only in the grammar they load. All three are in `DEEP_ADAPTERS`,
so `codeatlas scan` reports TypeScript, TSX and JavaScript files at the deep tier.

## Why

- **One implementation, three grammars.** The TypeScript grammar is built on top of the
  JavaScript one, so the node types we read (`call_expression`, `member_expression`,
  `method_definition`, `import_statement`...) are named the same in all three. The few
  differences are handled where they occur: a JavaScript class writes `extends Base`
  directly inside `class_heritage`, TypeScript wraps it in an `extends_clause`; only
  TypeScript has `interface_declaration` and `import x = require("x")`. Rejected: three
  adapters (three copies of every rule to keep in step).
- **One module per concern**, as T01 does for Python: symbols, imports, calls, routes and
  HTTP calls each walk the tree on their own. A file is walked five times instead of once,
  but each module reads alone, and walking a tree is cheap next to parsing it.
- **Keys are assigned after the walk.** A name that repeats in one scope (a getter and a
  setter `label`, two tests called `works`) needs T00's suffix: `#` plus a short hash of
  the signature, with `-2` only for identical signatures. Children's qualnames are built
  from their parent's, so the walk first records each definition with its parent and a
  *local* name, and keys are assigned outer-first afterwards. The suffix itself comes from
  T00's `_duplicate_suffixes`, imported from `generic/adapter.py` so a symbol gets the
  same key from either tier.
- **Calls are attributed by walking up the tree.** Each definition remembers its tree node;
  for a call, the adapter climbs its parents until it meets a function, method or test.
  Anonymous callbacks are not definitions, so `rows.map((r) => format(r))` inside
  `fetchAll` is a call from `fetchAll`, as the brief asks. Classes are skipped on the way
  up: a decorator or field initialiser is not inside any function, so it belongs to the
  module.
- **Callee text keeps its shape but not its arguments.** `router.route("/x").get((req,
  res) => { ... }).post` would drag a whole callback into the text, so arguments of calls
  inside a callee become `(...)`: `router.route(...).get(...).post`. A simple member chain
  such as `this.repo.save` is unchanged.
- **`require("x")` and `import("x")` with a literal are imports, not calls.** Python's
  `import` is not a call either, and counting them as unresolved calls would only add
  noise. `require(name)` with a variable is still a call: nothing can be said about it.
  Every literal `require` is an import wherever it sits: bound (`const x = require("x")`),
  or not (`require("dotenv").config()`, `app.use(require("./routes"))`,
  `module.exports = require("./x")`); the review found 20% of real requires in the
  unbound shapes.
- **Routes refuse what looks like a request.** `axios.get("/users", config)` has the same
  shape as `app.get("/users", handler)`. Names known to be axios clients (`axios` and any
  `axios.create` result) are excluded, the path must be a literal starting with `/`, and
  the last argument must not be a plain value (an object, string, number and so on), so
  `api.get("/users", { params })` on an imported client and `cache.get("/k", 1)` are not
  routes. `app.get("title")` (an Express setting) fails twice: no leading `/`, and no
  handler after it; `cache.get("key", fallback)` is rejected by the `/` rule alone.
- **Class expressions are classes.** `module.exports = class Repo extends Base {}` is a
  CLASS named `Repo`, and `const Svc = class {}` is a CLASS named by its variable, so
  their methods and calls are not credited to the module.
- **Inline and imported handlers use the module key.** A route's `handler_key` is the key
  of a function only when the handler is an identifier naming a top-level function in the
  same file. An inline arrow has no name, and an imported handler's key is only known after
  resolution (T07), so both get the module key in v1. Rejected: inventing `path::name` for
  an imported name (a key that points at nothing).
- **URL text keeps templates readable.** A literal loses its quotes (`/api/users`); a
  template loses its backticks but keeps `${id}` (`/api/users/${id}`), so the linker can see
  where parameters are and a base URL can be joined as plain text. When a part is dynamic
  the result stays an expression: `"/api" + "/profiles/" + id`.
- **Never raise.** tree-sitter builds a tree even for broken code; the adapter reports
  syntax errors with T00's `syntax_errors` and keeps every definition it could read. Any
  unexpected exception still returns the module node with `adapter failed: ...`.

## How

`parse(path, source, snapshot_id)`:

1. Emit the module node (T00's `module_node`) and parse with the adapter's grammar.
2. **Exports first.** Collect names exported by a separate statement: `export { a, b }`,
   `export default name`, `module.exports = name`, `module.exports = { a, b: c }` and
   `exports.x = name`. Declarations written with `export` in front are recognised where
   they stand.
3. **Definitions** (`symbols.py`), one walk with a small context (the enclosing definition
   and the current `describe` names):
   - `class` / `abstract class` → CLASS, with `bases` from `extends` and `implements`,
     decorators (on the class or before `export`), and the `/** ... */` comment above;
   - `interface` → INTERFACE with its `extends` list; type aliases are skipped;
   - `function` declarations at any depth → FUNCTION (`outer.inner` when nested);
   - at module level, `const f = () => ...` and `const f = function ...` → FUNCTION,
     signature from `const` to the body;
   - `export default () => ...` or an anonymous default function or class → named `default`;
   - methods inside a class → FUNCTION `Class.method` with `owner_key`, decorators, and
     `exported` copied from the class;
   - methods and function-valued properties of an **exported** object literal → FUNCTION
     `object.method` (no `owner_key`: the object is not a node);
   - in a test file (`*.test.*`, `*.spec.*`, `__tests__/`): `describe("A", ...)` pushes `A`;
     `it("b", ...)` or `test("b", ...)` becomes a TEST named `b`, qualname `A > b`, with
     `attrs["test_id"]` the same string. `.only`, `.skip`, `.concurrent`, `.todo` and
     `xit`/`fit` spellings count too.
4. **Qualnames**: outer first, `parent.qualname + "." + local name`, with T00's suffix for
   repeated local names in one scope.
5. **Imports**, **calls**, **routes** and **HTTP calls**: one walk each over the tree, using
   step 3 to find each call's caller.

Worked example (`client.ts`):

```ts
const api = axios.create({ baseURL: "/api" });

export function getProfile(id: string) {
  return api.get(`/profiles/${id}`);
}
```

- Nodes: module `client.ts::`, then FUNCTION `client.ts::getProfile`, signature
  `function getProfile(id: string)`, `exported: True`, `is_async: False`.
- Clients: `{"axios": no base, "api": base "/api"}`.
- Calls: `axios.create` from the module key (line 1), `api.get` from
  `client.ts::getProfile` (name `get`, receiver `api`).
- HTTP call: `RawHttpCall("client.ts::getProfile", "axios", "/api/profiles/${id}",
  "template", "GET", 4)`.
- No route: `api` is an axios client, so `api.get(...)` is a request, not an endpoint.

## Where

- **Contract types**: `Node`, `NodeKind`, `Span`, `RawImport`, `RawCall`, `RawRoute`,
  `RawHttpCall`, `ParseResult`, `Tier` and the id helpers from `models.py`; the adapters
  satisfy the `LanguageAdapter` protocol in `indexer/adapter.py`.
- **T00 helpers**: `module_node`, `syntax_errors` and the private `_Definition` /
  `_duplicate_suffixes` from `indexer/generic/adapter.py`; `extensions_for` from
  `indexer/discover.py`, so the adapters claim exactly the extensions discovery maps.
- **Registry**: three entries in `DEEP_ADAPTERS`; the registry falls back to the tags tier if
  an adapter fails to load.
- **Downstream**: the TS resolver (T07) turns imports and calls into IMPORTS, CALLS and
  INHERITS edges using `names`, `alias`, `is_reexport`, `receiver` and `bases`; the HTTP
  linker (T11) matches `RawHttpCall.url_text` against `RawRoute.path_pattern`.

### Known limitations (v1)

- Inline or imported route handlers get the module key (see Why). Routes mounted with
  `app.use("/v1", router)` are not prefixed here; `router` names the variable so the linker
  can do it.
- `describe.each(...)` / `it.each(...)` tables are not expanded into tests.
- Class fields holding arrow functions (`handleClick = () => {}`) and functions assigned to
  `exports.x = function ...` are not FUNCTION nodes; their calls belong to the module.
- Nested functions inside an object-literal method are named from the module, not the
  object (`inner`, not `api.get.inner`).
- An axios client is recognised only when created with `axios.create` in the same file and
  bound with `const`/`let`/`var`; `this.client = axios.create(...)` is not followed.
