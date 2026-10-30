# T07: TypeScript and JavaScript resolver (deep tier)

**Wave**: 2 (after T18, parallel with T06 and T16)
**Branch**: keep the one the cloud environment gives you

## Goal

Turn the TypeScript and JavaScript adapter's raw imports and calls (T02) into IMPORTS, CALLS, INHERITS and TESTS edges with the contract's resolution levels and confidences, following Node and TypeScript module resolution, and measure precision and recall on the fixture and against the SCIP oracle.

## Work in two phases

**Phase 1, plan (then stop).** Read this brief, `docs/contract.md` (sections 4, 5 and 7), `eval/fixtures/polyglot_app/LABELS.md` and the T02 adapter's output on the fixture's frontend. Write `docs/plans/T07.md`, at most about one page: how an import specifier becomes a file (one example per kind in the fixture), the rule for each resolution level with one real call from the fixture, your answers to "Decide in your plan", the tests, and what you expect to get wrong. Commit it, push, open a draft pull request titled `T07: TypeScript and JavaScript resolver`, and stop with the message "Plan ready for review". Write no resolver code until the owner replies.

**Phase 2, build.** When the owner replies, run `git pull origin main` first, apply the owner's changes to the plan, then build.

## Files you may create or edit

- `src/codeatlas/indexer/languages/typescript/resolver/` (new package)
- Registration: one line in `RESOLVERS` in `src/codeatlas/indexer/pipeline/plugins.py`: `"typescript": "codeatlas.indexer.languages.typescript.resolver:TypeScriptResolver"`, whose `languages` is `{"typescript", "tsx", "javascript"}`. T06 and T16 add lines to the same dictionary in parallel, so change nothing else in that file.
- `tests/indexer/typescript/resolver/`, `tests/data/typescript_resolver/`
- `docs/plans/T07.md`, `docs/explainers/typescript-resolver.md`

## Module resolution

1. **Relative specifiers** (`./api`, `../types`): try the path as written, then with `.ts`, `.tsx`, `.d.ts`, `.js`, `.jsx`, `.mjs`, `.cjs`, then `<dir>/index.*` in the same order. A `.js` specifier may name a `.ts` file (TypeScript's ESM convention).
2. **tsconfig paths**: read every `tsconfig.json` (and one level of `extends`); apply `compilerOptions.baseUrl` and `paths` to the files under that config's folder. tsconfig allows comments and trailing commas: strip them with a small tolerant reader (no new dependency); a config that still fails to parse is reported, never fatal.
3. **Workspace packages**: a bare specifier naming a package from T15's manifests (`@acme/ui`) resolves through that package's `exports` (the `"."` entry, string or `import`/`default` condition), `module`, `main`, `types`, or `index.*`, under the package root.
4. **Anything else** (`react`, `node:fs`, `lodash/merge`) is external: `::external:<specifier>` (decision D-19).

## What to resolve

`LABELS.md` is the specification for every case it covers; where this brief and the labels disagree, follow the labels and say so in the pull request.

**IMPORTS** (`STRUCTURAL`, 1.0): Module → Module for side-effect and namespace imports; Module → the symbol for named and default imports (a default import goes to the module's `default` export, or the symbol it names). **Follow re-exports**: an import through a barrel (`export {a} from`, `export * from`) is resolved to the real definition, as the labels require, with a cycle guard and at most five hops. The barrel itself gets an IMPORTS edge to each symbol it re-exports.

**CALLS**, one edge per (caller, callee) pair at the first line:

| Level | When | Confidence |
| --- | --- | --- |
| `DIRECT` | The name is defined in the caller's module or bound by an import or `require`; `ns.f()` through a namespace import; a JSX element `<UserCard />` | 1.0 |
| `SELF_METHOD` | `this.m()` on the enclosing class or a class it extends (bases resolved through imports) | 0.9 |
| `IMPORT_SCOPED` | The receiver's type is unknown and `name` is defined in the caller's file or the files it imports | 1 ÷ candidates |
| `NAME_GUESS` | Otherwise, same-named functions in the repository's TS/JS files | 1 ÷ candidates, at most 0.3 |

- `new Foo()` goes to Foo's written `constructor`; a class without one gets no edge (labels).
- A call on an external binding (`axios.get`, `React.useState`) goes to `::external:<specifier>.<name>`; well-known globals with no local binding (`console.log`, `JSON.parse`, `setTimeout`, `fetch`) go to `::external:globals.<name>`.
- HTTP calls are left to the linker (T11); this resolver does not touch `RawHttpCall`s.

**INHERITS**: `extends` and `implements` in `attrs["bases"]`, resolved like names, to a class or interface (`STRUCTURAL`, 1.0) or an external.

**TESTS**: for each TEST node, a TESTS edge to every non-test function it calls directly, with that call's resolution and confidence.

## Decide in your plan

1. **Typed receivers**: `const api = new UserApi(); api.getUser(7)`, or a parameter typed `api: UserApi`. Which level and confidence? Choose consistently with T06's plan if you can see it (draft pull request `T06: Python resolver`); otherwise argue for one and flag it for the owner.
2. **Name-guess cut-off**: above how many candidates does a name guess give up? Use the owner's answer to Q2 in `docs/decisions.md` if it is there.
3. **Mixed JS and TS**: may a `.js` file's call resolve to a `.ts` definition (and the reverse) at the name-guess level? The contract keeps guesses inside one language; `typescript`, `tsx` and `javascript` are three grammar names but one language family here.

## Tests

Small samples in `tests/data/typescript_resolver/` with exact expected edges: every specifier form above, a tsconfig with `baseUrl`, `paths` and `extends` (with comments and a trailing comma), a workspace package with `exports`, a barrel chain of two hops and a cycle, default and namespace imports, `require`, `this.m()` on an inherited method, a JSX component, a written and an unwritten constructor, globals, an external call, and a name guess. Use an in-memory `GraphStore`; no network.

## Measure and report

In the pull request:

- `python scripts/score_fixture.py`: precision, recall and F1 for TypeScript IMPORTS, CALLS, INHERITS and TESTS, and the calibration table. Explain every remaining false positive and false negative.
- The same export against the SCIP oracle file in `eval/oracle/references/` (TypeScript calls).
- `codeatlas index` on one real TypeScript repository of medium size with a tsconfig `paths` setup (choose one and say why): time, CALLS by level, the share of raw calls left unresolved, and the five most common unresolved callee names with why.

## Done when

Tests pass on Linux and Windows CI; the plan was approved and is committed; the scores are in the pull request; the explainer covers module resolution step by step, each resolution level with an example from the fixture, and what static resolution cannot see (dynamic property access, callbacks, framework magic).
