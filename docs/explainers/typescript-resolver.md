# TypeScript and JavaScript resolver

## What

The adapter (T02) reads one file at a time, so all it can say is "this file imports `./api`" and "this function calls `api.getUser`". The resolver reads every TypeScript, TSX and JavaScript file's raw items together and decides what each one points at. Its output is four kinds of edge: IMPORTS (a file to the symbol it really uses), CALLS (a function to the function it runs), INHERITS (a class to its base or interface) and TESTS (a test to the source function it exercises). Each edge carries how it was found and how sure we are.

## Why

- **Follow the real definition, not the barrel.** `import { UserApi } from "../src/api"` lands in `api/index.ts`, which only re-exports. The fixture labels want the edge to `client.ts::UserApi`, because an impact question ("what breaks if `UserApi` changes?") must not stop at a re-export file. So exports are followed, with a five-hop limit and a visited set, so a cycle of `export *` ends.
- **Everything in memory.** The resolver builds its own tables from the parse results (name to nodes, class to members, file to top-level symbols) instead of asking the store per call. The 650-file excalidraw repository resolves in about five seconds in total with parsing.
- **Levels instead of one score.** An edge found by following a name is certain; one found by "a function with that name exists in a file I import" is not. Keeping the level (and 1 ÷ candidates) lets search and impact ranking weigh them. Rejected: a single "resolved or not" flag.
- **A cut-off of five candidates.** Above that, a same-name match is mostly noise (`get`, `map`), so it gives no edge. Rejected: always emitting the best guess; it would flood the graph with 0.1 edges.
- **JS and TS are one family.** A `.js` file in a mixed repository calls `.ts` code; keeping them apart would lose real edges.
- **No dependency for tsconfig.** tsconfig allows comments and trailing commas; `jsonc.py` strips them with a 60-line scanner that leaves strings alone.
- **A config that fails to parse is a note, not a crash.** `TypeScriptResolver.problems` lists it.
- **Typed receivers only from what is written down (T20, D-22).** `repo.save()` with `repo: UserRepo` declared resolves to `UserRepo.save` at SELF_METHOD 0.9, like Python's T06: the declared class is known, but a subclass instance could be passed, so not 1.0. The types come from text the adapter already stores (signatures, JSDoc) plus one new class attribute, `attrs["fields"]`; the resolver never re-parses a file. Rejected: running the TypeScript compiler (a Node dependency, and it would execute project config), and inferring types from assignments (the adapter records none, and a wrong inference is worse than an honest IMPORT_SCOPED 1 ÷ n).
- **When in doubt, untyped.** A union of two classes, `any`, a type parameter, an array or a promise names no single class, so the call is resolved exactly as before. A typed receiver is tried before the built-in stop-list (with a declared `Cache`, `cache.get()` is `Cache.get`) and before imports (a typed parameter hides an import of the same name).

## How

### Module resolution (`modules.py`), in order

1. **Relative** (`./api`, `../types`): join onto the importer's folder, then try the path as written, then with `.ts .tsx .d.ts .js .jsx .mjs .cjs`, then the `.js` name standing for a `.ts` source (`./swap.js` -> `swap.ts`), then `<dir>/index.*`. A relative path that matches no file gives no edge (not an external).
2. **tsconfig `paths`**: the nearest tsconfig above the importer that has `paths` or `baseUrl` applies. Exact keys win, then the wildcard key with the longest prefix; `*` is substituted into each target, which is joined to the folder `paths` is relative to (`baseUrl` if set, else the config's folder), then resolved like a relative path. One level of `extends` is read; a setting remembers the folder of the file that wrote it.
3. **tsconfig `baseUrl`**: a bare specifier is tried under the base folder (`src/lib/thing` with `baseUrl: "."`).
4. **Workspace package**: `@acme/ui/sub` is split into package name and subpath; a PACKAGE node with that name (from T15) gives the root. For `.`: `exports["."]` (string, or the `import`, `default`, `types` conditions), then `module`, `main`, `types`; an entry that points into `dist/` is retried under `src/`; last `index.*` and `src/index.*`.
5. **Otherwise external**: `::external:<specifier>` (D-19).

### Names and edges

Each file gets a table of what its imports bound: a `symbol`, a `module` (a variable, so the edge goes to its file), a `namespace` (`* as ns`, `require`) or an `external`. Then for each call, the first rule that applies wins:

| Level | Rule | Fixture example |
| --- | --- | --- |
| DIRECT 1.0 | name defined in the file (or nested in the caller), bound by an import, `ns.f()`, `Class.staticMethod()`, a JSX element; `new C()` goes to `C.constructor` and a class with none gets no edge | `UserList` renders `<UserCard />`: CALLS `UserList -> UserCard`; `fetchUser(id)` in `getUser` |
| DIRECT to an external | the receiver or name is bound to a package, or is a known global with no binding | `axios.get` -> `::external:axios.get`; `console.log` -> `::external:globals.console.log` |
| SELF_METHOD 0.9 | `this.m()` / `super.m()`: the enclosing class, then its bases (resolved through imports, at most six levels) | `UserApi.getUser` calls `this.remember(user)` |
| SELF_METHOD 0.9, typed | the receiver's class is declared (see below); the method is found on it or its bases. Tried before every other rule | `r.save()` with `(r: Repo)` -> `UserRepo.save` |
| IMPORT_SCOPED 1 ÷ n | receiver type unknown; `name` is a function defined in this file or a file it imports (barrels expanded to the files behind them) | `api.getUser(7)` in the test: one `getUser` among the imported files, so 1.0 |
| NAME_GUESS min(0.3, 1 ÷ n) | otherwise, any function with that name in TS or JS files | `o.lonely()` -> the one `lonely` elsewhere, 0.3 |

Worked example: in `client.test.ts`, `const api = new UserApi(); await api.getUser(7)`. `UserApi` is imported from `../src/api`, which re-exports it from `./client`, so the import binds `UserApi` to `client.ts::UserApi` and `client.ts` joins the files the test imports. `new UserApi()` is DIRECT but the class has no written constructor: no edge. `api.getUser`: the receiver `api` is a local variable, so no rule decides; the scoped step finds exactly one `getUser` function in imported files (`UserApi.getUser`), so the edge is IMPORT_SCOPED 1.0. Because the caller is a TEST and the target is a source function, a TESTS edge with the same level is added.

### Typed receivers (`types.py`)

For a receiver `head.a.b` (at most three hops):

1. **Find the head's declared type.** `this` is the enclosing class. Otherwise `head` is looked up as a parameter of the caller, then of each function written around it, innermost first; the first function that declares the name decides, so an untyped inner parameter hides a typed outer one. The type text is the TypeScript annotation in the stored `signature` (a bracket-aware splitter takes the first top-level `(...)`, splits on top-level commas, drops `private`/`readonly`/`...`/defaults and skips destructured parameters), else the JSDoc `@param {Type} name` in the stored `docstring`.
2. **Each further hop is a field.** `this.repo` looks at the class, then its bases, nearest first: `attrs["fields"]` (written by `symbols.py` from `repo: UserRepo;`, `/** @type {UserRepo} */ repo;`, `repo = new UserRepo()`, and constructor statements `this.repo = new UserRepo()` or `/** @type {UserRepo} */ this.repo = ...`), then a constructor parameter of the same name (`constructor(private repo: UserRepo)`, or JavaScript's `@param {UserRepo} repo` + `this.repo = repo`).
3. **Type text to a name.** `type_name` drops JSDoc `?`/`!`/`=`, outer parentheses and `null`/`undefined`/`void` union members; exactly one member must remain, of the shape `Name` or `ns.Name` with optional generics (`Repo<User>` -> `Repo`). Intersections, arrays, `Promise<X>`, object/function/literal types, primitives, `any`, `unknown`, and type parameters (`<T>` of the caller, the functions around it or the class, and JSDoc `@template T`) give nothing.
4. **Name to class.** The same name resolver as INHERITS (local class, import binding with aliases and barrels, `ns.X`); it must be a CLASS. Interface method signatures are not nodes, so an interface type gives nothing.
5. **Method.** Found on the class or its bases: SELF_METHOD 0.9. Not found and the class extends a library class: no edge. Not found otherwise: the call falls through to the old rules.

Worked example (`tests/data/typescript_resolver/typed`): `service.ts` imports `{ UserRepo as Repo }` and declares `constructor(private repo: Repo)`. In `viaProperty`, `this.repo.save("a")` has receiver `this.repo`: the class `Service` has no `repo` field, but its constructor's signature has the parameter `repo` with text `Repo`; `type_name` keeps `Repo`, the import binding maps it to `repo.ts::UserRepo`, which defines `save`: CALLS `Service.viaProperty -> UserRepo.save`, SELF_METHOD 0.9. In `onUnion(both: Repo | Other)` the union has two members, so `both.save()` stays IMPORT_SCOPED 0.5 to both `save` methods, as before T20.

**INHERITS**: each `bases` entry has its generics cut (`Base<T>` -> `Base`), is resolved like a name (local class, imported symbol, `ns.Base`, an external `react.Component`), and gives an edge to a class or interface.

**Duplicates**: one edge per (source, target, kind); the best confidence, the first line.

## Where

- Reads the contract's `ParseResult`, `RawImport`, `RawCall`, `Node`, and the `SymbolIndex` only for `files()` and `by_name` (PACKAGE nodes).
- Writes `Edge` with `EdgeKind.IMPORTS`, `CALLS`, `INHERITS`, `TESTS` and the resolutions `STRUCTURAL`, `DIRECT`, `SELF_METHOD`, `IMPORT_SCOPED`, `NAME_GUESS`.
- Loaded by `indexer/pipeline/plugins.py` (`RESOLVERS["typescript"]`); the pipeline creates the EXTERNAL nodes and drops edges whose ends do not exist.
- Reading tsconfig and package.json needs the repository root, which `Resolver.resolve` does not receive: it uses the snapshot's local source folder (see the pull request).
- Typed receivers read `Node.signature`, `Node.docstring` and the class attribute `attrs["fields"]` (field name -> type text, written by `languages/typescript/symbols.py`).
- Measured with `python scripts/score_fixture.py`.

## What static resolution cannot see

- **Inferred types.** Only declared types count: `const api = new UserApi(); api.getUser(7)` is still an unknown receiver (locals are not recorded), as are return types (`make().save()`), interface-typed receivers (interface methods are not nodes) and `import("./x").Y` JSDoc types. With two imported classes both defining `save`, an unknown receiver gets 0.5 to each.
- **Dynamic access and callbacks.** `handlers[name]()`, `obj[method]()`, a function passed in as an argument and called there (`cb()`), `.call`, `.apply`, `bind`.
- **Framework magic.** Dependency injection, decorators that wire classes, file-system routing, string-named components.
- **Wrapped components.** `export const Excalidraw = React.forwardRef(...)` is a variable, not a function node, so `<Excalidraw />` gets no edge (371 raw calls in excalidraw).
- **`export { a as b }` with no `from`**, because the adapter emits no raw item for it; a default import of a named `export default class K` goes to the module, since the adapter does not mark which symbol is the default.
- **Matcher chains.** `expect(x).toBe(1)`: `toBe` belongs to a library, so it stays unresolved.
