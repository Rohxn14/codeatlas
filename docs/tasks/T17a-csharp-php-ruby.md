# T17a: C#, PHP and Ruby through the add-language skill

**Wave**: 3 (all of Wave 3 runs in parallel)
**Branch**: keep the one the cloud environment gives you

## Goal

Give C#, PHP and Ruby import-scoped call resolution in the structural tier, by following `.claude/skills/add-language/SKILL.md` (T16) once per language. Today all three get name guesses only. This task is also the test of the skill: wherever it was unclear or wrong, fix the skill in the same pull request.

## Plan first, then build

Write `docs/plans/T17a.md` (about one page) as your first commit, then keep going without waiting: for each language, what an import looks like, how it maps to files (the resolution profile), the scope rules for unqualified and qualified calls, and what you expect to get wrong.

## Files you may create or edit

- `src/codeatlas/indexer/queries/c_sharp/`, `queries/php/`, `queries/ruby/` (imports queries; tags-query extras only if the skill's step 1 finds a gap)
- `src/codeatlas/indexer/structural/` (one profile module per language, and their registration where the skill says)
- `.claude/skills/add-language/SKILL.md` (corrections only)
- `tests/indexer/structural/` (new files with unique names, such as `test_php_profile.py`), `tests/data/structural/csharp/`, `php/`, `ruby/`
- `docs/plans/T17a.md`, `docs/explainers/structural-tier.md` (the language table and one paragraph per language)

## The three profiles

- **C#**: `using A.B;` brings a namespace; a namespace's files are those whose `namespace A.B` (block or file-scoped) declaration matches. Capture the declared namespace into the module node's `attrs["package"]`, as Java does. `using static A.B.C;` brings C's members; `using X = A.B.C;` is an alias. Calls on a class name resolve among that class's members in the namespaces in scope.
- **PHP**: `use App\Models\User;` (and grouped `use App\{A, B}`) maps through the PSR-4 map that T15 recorded in each Composer package's `attrs["autoload_psr4"]` (`App\` → `src/`), so `App\Models\User` is `src/Models/User.php`. `require`/`include` with a literal path is a file import. `User::find()` and `$x->save()` follow the same scope rules as Java.
- **Ruby**: `require_relative "x"` is a path relative to the file; `require "x"` maps to `lib/x.rb` (and the gem's own `lib/`) when that file exists, and is external otherwise. Classes reopened in several files are one scope. `Foo.bar` resolves among `Foo`'s methods; a bare `bar` looks in the enclosing class, then the file, then required files.

The cut-off stays at 5 candidates for name guesses and for untyped receivers (T16's rule).

## Tests

For each language: a small sample project with an `expected_graph.json` scored with `eval.oracle.score` (precision and recall for imports and calls), unit tests of its imports query on snippets, and its profile's file mapping. No network.

## Measure and report

In the pull request: per language, sample precision and recall; one real repository each (choose small or medium ones, say why; the acceptance suite in `eval/suite/repos.yaml` has candidates), with time, CALLS by level and the unresolved share before and after this task; and a list of every change you made to the skill and why.

## Done when

Tests pass on Linux and Windows CI; the plan is committed; the three languages show import-scoped edges on their samples and real repositories; the skill reads correctly for the next language.
