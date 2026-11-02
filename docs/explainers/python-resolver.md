# Python resolver (deep tier)

## What

`PythonResolver` reads what the Python adapter saw in each file (definitions, raw imports, raw calls) and turns it into four kinds of edge: IMPORTS (a file uses another file, a symbol, or something outside the repository), CALLS (a function or test runs another function), INHERITS (a class names a base) and TESTS (a test exercises a function). Every edge says how it was found (`Resolution`) and how sure we are (`confidence`). A call it cannot settle stays a raw call: there is no edge, and the evaluation can count it.

## Why

- **Only the raw items, no source.** The contract gives a resolver `ParseResult`s and a `SymbolIndex`, so it is pure and cannot execute indexed code. The price: it never sees an assignment such as `x = Foo()`. Types come only from what a signature declares.
- **Lookup tables, not an AST pass.** Each file gets a small table (definitions, nested functions, import bindings). Import bindings are stored as written and followed on demand, so a re-export chain costs nothing unless a name asks for it. Rejected: resolving every import eagerly (wasted work, and cycles); a full type inferencer (needs assignments we do not have).
- **Typed receivers are `SELF_METHOD` 0.9** (decision 1 in `docs/plans/T06.md`). The method is found through a class's bases exactly like `self.m()`, and a declared type can still be a subclass that overrides it, so 1.0 would overclaim. Rejected: `DIRECT` (overclaims) and a new level (contract change for no gain).
- **An honest "I don't know".** A method missing from a class whose bases are not all in the repository stays raw instead of being guessed: it probably lives in the library base.
- **Guesses are capped and rationed.** Above 5 candidates, or for a container method name such as `get`, `append` or `join`, no guess is made. The caller itself is never a candidate (`self.items.get()` inside `Repo.get` is a dict call, not recursion).

## How

1. **Module map** (`project.py`). Roots are `""`, `src`, each package root from T15 (read through `index.by_key(package_key)`), and the importing file's folder. `import a.b` is the file `root/a/b.py` or `root/a/b/__init__.py` under any root; several hits split the confidence, unless some sit in the importer's own package. A relative import climbs `level - 1` folders from the importer.
2. **Tables** (`tables.py`). Per file: top-level definitions by plain name (the last of several `#hash` redefinitions wins, as in Python), nested functions, and bindings: `import a.b.c` binds `a`, `a.b` and `a.b.c`; `from m import n as x` binds `x` to `(m, n)`.
3. **Names** (`names.py`). `ref(path, "UserRepo.save")` starts at a definition, an import or a builtin, then walks one part at a time: into a module's exports (definition, then re-export up to three hops, then submodule), into a class's members through its MRO (depth-first, left to right, ten deep; an unresolvable base marks the MRO incomplete), or onto an outside name (`os` + `path` = `::external:os.path`).
4. **Calls** (`calls.py`), first answer wins. (a) A parameter of the caller or an enclosing function: leave raw. (b) A nested function, then `ref`: DIRECT; a class goes to the `__init__` that runs, inherited or not, and none means no edge. (c) `self`/`cls`/`super()`: SELF_METHOD through the bases. (d) A dotted receiver that is a module or class: DIRECT. (e) A receiver with a declared class (parameter annotation, `self.x` matching an annotated `__init__` parameter, `Cls(..)`, or a call to a function with a return annotation): SELF_METHOD 0.9. (f) Unknown receiver: methods of that name in the caller's file and the files it imports (IMPORT_SCOPED, 1 ÷ n); else anywhere in the repository (NAME_GUESS, 1 ÷ n, at most 0.3).
5. **IMPORTS, INHERITS, TESTS** (`edges.py`, `resolver.py`). An imported name goes to its definition through re-exports, to a submodule, or (a variable such as `router`) to its module. A base resolves like a name. A TESTS edge copies each CALLS edge from a test to a function outside the test files.

Worked example, from the fixture. `services.py` has `self.repo.save(user.id, user)` in `UserService.create_user`.

1. The receiver is `self.repo`, a single attribute on `self`.
2. `UserService.__init__(self, repo: UserRepo)` has a parameter named `repo` annotated `UserRepo`. In `services.py`, `UserRepo` is bound by `from .user_repo import UserRepo`, which is the class in `user_repo.py`.
3. `UserRepo`'s MRO is `[UserRepo, Repo]` (the base `BaseRepo` is bound by `from .repo import Repo as BaseRepo`). `save` is found on `UserRepo` first.
4. Result: `UserService.create_user -> UserRepo.save`, `self_method`, 0.9, line 19. `self.repo.get(user_id)` in `get_user` finds `get` only on `Repo`, the second class of the MRO.

Other levels on the same fixture: `@logged` is `DIRECT` to `decorators.py::logged` (D-11); `UserRepo()` is `DIRECT` to `Repo.__init__`, which `UserRepo` inherits; `service.get_user(id)` in `routes.py` has an untyped receiver (a module variable), so `IMPORT_SCOPED` finds one method named `get_user` in the files `routes.py` imports (1.0); `len(...)` is `::external:builtins.len`; `func(*args)` in `logged.wrapper` calls a parameter and `HANDLERS[name](...)` is a subscript, and both stay raw.

## Where

- Reads: `ParseResult` (nodes, imports, calls), `SymbolIndex.by_key` (package nodes for roots). Registered in `indexer/pipeline/plugins.py`; `build_graph` runs it and creates the EXTERNAL nodes for `::external:` targets (D-19).
- Contract types: `RawImport`, `RawCall`, `Node` (`attrs["bases"]`, `signature`, `owner_key`), `Edge`, `EdgeKind` (IMPORTS, CALLS, INHERITS, TESTS), `Resolution`.
- Measured with `scripts/score_fixture.py`; results are in the pull request.

### What it cannot see

- **Locals and duck typing.** `x = Foo(); x.run()`, `client = TestClient(app); client.get()` and every call on a fixture parameter without an annotation (`runner.invoke` in click's tests) have no known type. They fall to IMPORT_SCOPED or stay raw.
- **Attributes set outside `__init__`**, properties, and instances held in module variables (`service = UserService(..)`).
- **Dynamic calls**: `getattr(obj, name)()`, `HANDLERS[name]()`, `setattr`, decorators that replace a function, monkeypatching.
- **Conditional imports** and `__all__` are not modelled; all imports in a file are visible everywhere in it.

### What v2 could do

Ask the adapter for local assignments and attribute assignments (`x = Foo()`, `self.repo = repo`) so receivers get types from where they are made rather than from naming conventions; follow `__all__` and `TYPE_CHECKING` imports; use a SCIP index as the answer key for which guesses to trust; compute C3 linearisation for diamond inheritance.
