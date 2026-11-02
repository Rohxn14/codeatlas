# T16: Structural framework, with Java and Go first

**Wave**: 2 (all of Wave 2 runs in parallel)
**Branch**: keep the one the cloud environment gives you

## Goal

Today the structural tier finds definitions and calls in twelve languages but resolves nothing, so those languages have no CALLS or IMPORTS edges at all. This task builds the framework that gives any tree-sitter language import-scoped resolution from three small pieces, with no new code paths per language:

1. a **tags query** (exists for every grammar) for definitions and calls;
2. an **imports query** (`queries/<language>/imports.scm`) for import statements;
3. a **resolution profile**: how an import string maps to files, and which files a call may reach.

One import-scoped resolver serves every language that has a profile, and every other structural language gets name-guess resolution, so each language has some CALLS edges. Java and Go are the first two profiles. The procedure is written down as an add-language skill, so later sessions (T17a, T17b) and the owner add a language by following it.

## Plan first, then build

Before writing code, write `docs/plans/T16.md` (at most about one page) as described below, and commit it as your first commit. Then build without waiting: the owner reviews plans and code together at the end of the day, and the plan is how he follows your reasoning. If a decision in the plan turns out wrong while building, update the plan in the same commit as the change.

The plan covers: the approach and its data structures; the rule for each resolution level with one real example from the fixture (or your samples); your answers to "Decide in your plan" below, each with one line of why; the tests; and what you expect to get wrong.

The pipeline exists (`src/codeatlas/indexer/pipeline/`; read `docs/explainers/pipeline.md`): your resolver's entry is already in `plugins.py`, so once the class exists `build_graph` runs it. Measure with `python scripts/score_fixture.py`, which indexes the fixture and scores it against the hand labels (`--truth eval/oracle/references/oracle_polyglot_app_061bf641daff.json` scores against the SCIP oracle). Resolvers return edges only: point an edge at `::external:<name>` for something outside the repository and the pipeline creates the EXTERNAL node (contract section 4).

## Files you may create or edit

- `src/codeatlas/indexer/structural/` (new package): the resolver and the profiles
- `src/codeatlas/indexer/generic/adapter.py`: run an imports query when one exists and emit `RawImport`s; fix `_signature` (below). T01 and T02 import `module_node`, `syntax_errors`, `_Definition` and `_duplicate_suffixes` from this file: keep those names and their behaviour.
- `src/codeatlas/indexer/queries/java/`, `src/codeatlas/indexer/queries/go/`, `src/codeatlas/indexer/queries/README.md`
- Registration is already done: `RESOLVERS` in `src/codeatlas/indexer/pipeline/plugins.py` has the entry `"structural": "codeatlas.indexer.structural:StructuralResolver"`. Make that import path work and do not edit `plugins.py`.
- `.claude/skills/add-language/SKILL.md`
- `tests/indexer/structural/`, `tests/data/structural/`, and existing tests of the generic adapter where `_signature` changes them
- `docs/plans/T16.md`, `docs/explainers/structural-tier.md`

## Part 1: imports queries

Extend the tags adapter: when `queries/<language>/imports.scm` exists, run it and turn its captures into `RawImport`s (target as written, imported names, alias). Define the capture names once in `queries/README.md`. Write the Java and Go queries:

- **Java**: `import a.b.C;`, `import a.b.*;`, `import static a.b.C.m;`, `import static a.b.C.*;`, plus the file's `package` declaration (record it in the module node's `attrs["package"]`).
- **Go**: single and grouped imports, aliases (`f "fmt"`), dot imports and blank imports (`_ "x"`), plus the `package` clause (module node `attrs["package"]`).

## Part 2: resolution profiles and the resolver

A profile answers, for one language: which files an import string reaches, and which files a call may resolve into (its scope). The resolver does the rest the same way for every language:

| Level | When | Confidence |
| --- | --- | --- |
| `IMPORT_SCOPED` | `name` (or `qualifier.name` where the qualifier is an import) is defined in the caller's file, in its package scope, or in the files its imports reach | 1 ÷ candidates |
| `NAME_GUESS` | No profile for this language, or nothing in scope: same-named definitions anywhere in that language | 1 ÷ candidates, at most 0.3 |

IMPORTS edges come from the profile (`STRUCTURAL`, 1.0, split across candidates); a target outside the repository becomes `::external:<target>` (decision D-19). Calls stay raw when nothing matches.

- **Java profile**: `a.b.C` maps to a file whose path ends in `a/b/C.java` under any source root (`src/main/java`, `src/test/java`, `src`, or the repository root); `a.b.*` maps to every `.java` file in a folder ending `a/b`. Files with the same `package` declaration are in scope without an import. `C.m()` with `C` imported resolves among `C`'s members; an unqualified `m()` looks in the same class, then the same package.
- **Go profile**: strip the module path from T15's Go package attrs (`go.mod`, and `go.work` members) to turn an import path into a directory; a package is every non-test `.go` file in that directory. `pkg.F()` resolves among the definitions in `pkg`'s directory; an unqualified `F()` resolves in the caller's own directory. Standard library and third-party paths are external.

`languages` is every structural-tier language in the registry. Languages without a profile get name guesses only, and the explainer lists which have which.

## Part 3: fix T00's `_signature`

`_signature` in `generic/adapter.py` copies every line between the start of a definition and its body, including comments between a Python `def ...:` and the first statement. That text feeds the `#hash` suffix for repeated names, so the deep and structural tiers give different keys for 59 of 4,646 site-packages files (T01 review), and editing such a comment changes a key. Stop the signature at the end of the definition's header and drop comments. Add a test that the deep Python adapter and the tags adapter give identical keys on a sample with repeated, commented definitions.

## Part 4: the add-language skill

`.claude/skills/add-language/SKILL.md`: the procedure a session follows to give a new language structural depth: check the grammar loads and its tags query finds definitions and calls; write `imports.scm` and test it on snippets; write the profile; write a small sample project with a hand-labelled expected graph; register; score; update the explainer's language table. Write it as instructions another session can follow alone, with the Go profile as the worked example. T17a and T17b will use it; the owner will test it by adding one language himself.

## Decide in your plan

1. **Go package imports**: an import reaches every file of a directory. Do IMPORTS edges go to each file (how many at most?), or to one file, or is there a better target within the contract?
2. **Name-guess cut-off**: above how many candidates does a name guess give up? Use the owner's answer to Q2 in `docs/decisions.md` if it is there.
3. **Java overloads and inner classes**: what keys do they get from the tags tier today, and does the resolver need to tell overloads apart?

## Tests

Small sample projects in `tests/data/structural/java/` (two or three packages, a wildcard import, a static import, same-package calls) and `tests/data/structural/go/` (a `go.mod` module with three packages, an aliased import, same-package calls, a `_test.go` file), each with an `expected_graph.json` in the scorer's format. Unit tests for both imports queries, both profiles, name guesses in a language without a profile (for example Ruby), and the `_signature` fix. No network.

## Measure and report

In the pull request: precision and recall per edge kind on the Java and Go samples (with `eval.oracle.score`); `codeatlas index` on one real Go and one real Java repository of medium size (choose and say why): time, CALLS by level, the share of raw calls left unresolved; and the same unresolved share for three structural languages without a profile.

## Done when

Tests pass on Linux and Windows CI; the plan is committed; scores are in the pull request; the skill exists; the explainer covers the three pieces, the resolver's steps with a Go worked example, and which languages have which depth.
