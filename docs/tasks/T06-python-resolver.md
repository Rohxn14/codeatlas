# T06: Python resolver (deep tier)

**Wave**: 2 (after T18)
**Branch**: keep the one the cloud environment gives you

## Goal

Turn the Python adapter's raw imports and calls (T01) into IMPORTS, CALLS, INHERITS and TESTS edges, each with the resolution level and confidence the contract defines, and measure precision and recall on the fixture and against the SCIP oracle. This is the first piece the owner will rewrite as v2 after Nov 4, so the explainer and the plan matter as much as the code.

## Work in two phases

**Phase 1, plan (then stop).** Read this brief, `docs/contract.md` (sections 4, 5 and 7), `eval/fixtures/polyglot_app/LABELS.md` and the T01 adapter's output on the fixture's backend. Write `docs/plans/T06.md`, at most about one page:

- how module names map to files, with one example per kind of import in the fixture;
- for each resolution level, the rule that picks it, with one real call from the fixture;
- the decisions listed under "Decide in your plan" below, each with your choice and one line of why;
- the tests you will write and how you will measure;
- what you expect to get wrong.

Commit it, push, open a draft pull request titled `T06: Python resolver`, and stop with the message "Plan ready for review". Write no resolver code until the owner replies.

**Phase 2, build.** When the owner replies, first run `git pull origin main` (T18's pipeline may have merged since you started), apply the owner's changes to the plan, then build.

## Files you may create or edit

- `src/codeatlas/indexer/languages/python/resolver/` (new package)
- Registration: one line in `RESOLVERS` in `src/codeatlas/indexer/pipeline/plugins.py`: `"python": "codeatlas.indexer.languages.python.resolver:PythonResolver"`. T07 and T16 add lines to the same dictionary in parallel, so change nothing else in that file.
- `tests/indexer/python/resolver/`, `tests/data/python_resolver/`
- `docs/plans/T06.md`, `docs/explainers/python-resolver.md`

## What to resolve

The fixture's `LABELS.md` is the specification for every case it covers; where this brief and the labels disagree, follow the labels and say so in the pull request.

**Module map.** Map dotted module names to files: absolute imports from the repository root, from a `src/` folder, and from each Python package root that T15's manifests found; `__init__.py` is its package's module; relative imports climb `level` packages from the importing file. Several files matching one import split the confidence.

**IMPORTS** (resolution `STRUCTURAL`, confidence 1.0, or split across candidates):
- `import a.b` and `from a import b` where `b` is a submodule: Module → Module.
- `from a import f`: Module → the symbol `f` defined in `a`; follow re-exports through `__init__.py` (`from .x import f`) up to three hops to the real definition.
- A target outside the repository: Module → `::external:<dotted name>` (decision D-19; the pipeline creates the EXTERNAL node). Standard library modules count as external.

**CALLS**, from each raw call's `caller_key`; one edge per (caller, callee) pair, at the first line:

| Level | When | Confidence |
| --- | --- | --- |
| `DIRECT` | The name is defined in the caller's module or imported into it: `helper()`, an alias from `import ... as`, `module.func()` through an imported module, a decorator (D-11) | 1.0 |
| `SELF_METHOD` | `self.m()` or `cls.m()` on the enclosing class or a base class found through the class's resolved bases; `super().m()` on the base class | 0.9 |
| `IMPORT_SCOPED` | The receiver's type is unknown, and `name` is defined in the caller's file or the files it imports | 1 ÷ candidates |
| `NAME_GUESS` | Otherwise: same-named functions anywhere in the repository's Python files | 1 ÷ candidates, at most 0.3 |

- A constructor call `Cls(...)` goes to the `__init__` that runs, including an inherited one; a class with no written `__init__` anywhere in its bases gets no edge (labels).
- A call on a module outside the repository (`requests.get`, `os.path.join`) goes to `::external:requests.get` with `DIRECT`; a Python builtin with no local binding (`len`, `print`) goes to `::external:builtins.len`.
- Deliberately unresolvable calls stay raw: `getattr(...)(...)`, `HANDLERS[name](...)`, calling a parameter.

**INHERITS**: each base in `attrs["bases"]`, resolved like a name, to a class in the repository (`STRUCTURAL`, 1.0) or an external.

**TESTS**: for each TEST node, a TESTS edge to every non-test function it calls directly, with that call's resolution and confidence. Module-level TESTS edges by naming convention already come from T15.

## Decide in your plan

1. **Typed receivers.** `self.repo = UserRepo()` in `__init__`, or an annotation (`repo: UserRepo`), tells you the type of `self.repo`, so `self.repo.save()` is `UserRepo.save` (the labels expect this). Which level and confidence does such an edge get? The contract has no "typed" level: argue for `SELF_METHOD` 0.9, `DIRECT`, or a contract change request.
2. **Local variables.** Does `x = Foo(); x.run()` count as a typed receiver too?
3. **Name-guess cut-off.** Above how many candidates should a name guess give up and leave the call raw? Use the owner's answer to Q2 in `docs/decisions.md` if it is there.
4. **Method resolution order.** How far you follow bases (multiple inheritance, bases imported from other files) and what happens at a base you cannot resolve.

## Tests

Small multi-file samples in `tests/data/python_resolver/` with exact expected edges for each row of the CALLS table, relative and absolute imports, `__init__.py` re-exports, aliases, inherited `__init__`, `super()`, a builtin, an external call, a name guess with three candidates (1 ÷ 3, capped at 0.3), and each unresolvable case. Use an in-memory `GraphStore` and its `symbol_index`; no network.

## Measure and report

In the pull request:

- `python scripts/score_fixture.py`: precision, recall and F1 for Python IMPORTS, CALLS, INHERITS and TESTS, and the calibration table for CALLS. Explain every false positive and false negative that remains.
- The same export scored against the SCIP oracle file in `eval/oracle/references/` (Python calls).
- `codeatlas index` on one real Python repository (for example `pallets/click`): time, CALLS by resolution level, the share of raw calls left unresolved, and the five most common unresolved callee names with why they stayed unresolved.

## Done when

Tests pass on Linux and Windows CI; the plan was approved and is committed; the scores are in the pull request; the explainer covers each resolution level with a worked example from the fixture, what the resolver cannot see (dynamic calls, duck typing), and what v2 could do about it. Incremental re-indexing is not part of this task (it moved to the local phase).
