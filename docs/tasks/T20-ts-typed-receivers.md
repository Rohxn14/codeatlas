# T20: Typed receivers for TypeScript and JavaScript (D-22)

**Wave**: 4 (runs in parallel with T19 and T21; no file overlap)
**Branch**: keep the one the cloud environment gives you

## Goal

JavaScript is the weakest deep language in the acceptance suite (22% of raw calls resolved; express 13%, lodash 4%), and TypeScript resolves a receiver call such as `repo.save()` only as `IMPORT_SCOPED` 1/n over every `save` in the imported files. The Python resolver (T06) already reads types from signatures and resolves `self.repo.save()` at `SELF_METHOD` 0.9. Bring the same to TypeScript and JavaScript, and finish decision D-22: typed receivers at `SELF_METHOD` 0.9 in both deep languages.

## Plan first, then build

Write `docs/plans/T20.md` (about one page) as your first commit, then keep going: the type sources below in order of trust, how a type name becomes a class node (imports, aliases, generics), what stays untyped, and what you expect to get wrong. Read `src/codeatlas/indexer/languages/python/resolver/types.py` first: copy its approach, not its code.

## Files you may create or edit

- `src/codeatlas/indexer/languages/typescript/resolver/` (a new `types.py` and the call resolver)
- `src/codeatlas/indexer/languages/typescript/symbols.py`: only to add node attrs (for example `attrs["fields"]` on a class: field name → type text) if the signature and JSDoc text already stored are not enough; say which in the plan
- `tests/indexer/typescript/resolver/` (new files with unique names, such as `test_ts_types.py`), `tests/data/typescript_resolver/`
- `docs/plans/T20.md`, `docs/explainers/typescript-resolver.md`

Do not edit `models.py`, `adapter.py`, the contract or the Python resolver.

## Type sources, most trusted first

1. TypeScript annotations in the function's `signature`: `(repo: UserRepo)`, return types for `const r = make()` only if a later step needs them (optional).
2. Constructor parameter properties (`constructor(private repo: UserRepo)`) and class field declarations (`repo: UserRepo;`, `repo = new UserRepo()`), for `this.repo.save()`.
3. JSDoc in the node's docstring: `@param {UserRepo} repo`, `@type {UserRepo}`, `@returns`, for JavaScript.
4. `new Foo()` assigned to a name in the same function, only if the adapter already records it (do not re-parse files in the resolver).

A type resolves through the file's import bindings and local classes to a CLASS or INTERFACE node; strip generics (`Repo<User>` → `Repo`), arrays, `| null`/`| undefined` and `Promise<>` only when awaited. Union of two classes, `any`, `unknown`, type parameters: untyped. A method found on the class or its INHERITS chain is `SELF_METHOD` 0.9; an interface method resolves to the interface's declaration (the implementation is not known statically).

## Rules that stay

Built-in method stop-list (T07), the 5-candidate cut-off, D-23 (no TESTS edges from name guesses). An untyped receiver behaves exactly as today.

## Tests and measure

- Unit tests per type source, each with exact edges, plus negative cases (`any`, a union, a type parameter, a shadowed name).
- The fixture: `python scripts/score_fixture.py` must not lose precision; report CALLS by resolution before and after.
- In the pull request: resolved share and CALLS by level before and after on `express`, `zod`, `is` and one more JavaScript repository of your choice from `eval/suite/repos.yaml` (shallow clone, at most two attempts each), and 20 sampled new `SELF_METHOD` edges checked by hand (how many are right).

## Done when

Tests pass on Linux and Windows CI; `ruff check .` passes; the plan is committed; the numbers and the hand check are in the pull request; `docs/decisions.md` is not edited (the owner records D-22), but the pull request says D-22 is now implemented in both languages. Pull request title: `T20: typed receivers for TypeScript and JavaScript`.
