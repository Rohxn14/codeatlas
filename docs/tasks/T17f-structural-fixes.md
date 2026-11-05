# T17f: Structural tier review fixes (C#, PHP, Ruby, C, C++, Rust)

> **Reading note.** This brief is history. It is what a cloud session was told to build, kept so you can see what was asked; it is not an instruction for new work.
> - **Built in**: pull request #33.
> - **Read first**: `docs/explainers/structural-tier.md` (section "Review fixes (T17f)"), for what was actually built and why.
> - **Code**: `src/codeatlas/indexer/structural/`. **Tests**: `tests/indexer/structural/test_structural_fixes.py`.
> - **Then** read this brief and its review at the end: the gap between them is where the interesting questions are.
> - Reading order, glossary and how to study a module: `docs/README.md`.

**Wave**: 3 fixes (runs in parallel with T11f and T12f; no file overlap)
**Branch**: keep the one the cloud environment gives you
**Why**: the reviews of T17a and T17b (end of their briefs). Both merged. The fixes are one session because they share `structural/resolver.py`. Most are wrong edges at confidence 1.0, the worst kind for the impact engine.

## Files you may edit

- `src/codeatlas/indexer/structural/` (resolver, profiles, `context.py`)
- `src/codeatlas/indexer/queries/c_sharp/`, `php/`, `ruby/`, `c/`, `cpp/`, `rust/`
- `tests/indexer/structural/` (new files with unique names, or the existing T17a/T17b test files), `tests/data/structural/`
- `.claude/skills/add-language/SKILL.md` (if a rule changes), `docs/explainers/structural-tier.md`

Every fix needs a test with the failing example below. After the shared resolver changes, the Java and Go samples and `python scripts/score_fixture.py` must not change.

## Must fix

1. **Rust `X::m()` with an unknown type lands on any `m` in the file, at 1.0** (`structural/rust.py:84`, then `resolver.py` `_in_scope`). With `struct A; impl A { fn new() -> A { A } }` in the file, `HashMap::new()` gives `A.new` 1.0 `import_scoped`; `T::new()` too. Add `RustProfile.narrow`: when the receiver's last segment starts with a capital, keep only nodes whose owner name equals it. This also stops `E::V(1)` → `A.V`.
2. **Rust `crate::`, `super::` and inline-module paths become 1.0 external edges** (`rust.py:84`, `rust.py:226`). `super::f()` in a file with no crate root gives `::external:super.f`; `mod inner { pub fn f() {} } fn g() { inner::f(); }` gives `::external:inner.f`. In `qualify`, return None (never an external) when the first segment is `crate`, `self` or `super`, or when a qualname in the file starts with `first + "."`.

## Should fix

3. **5-candidate cut-off skipped for untyped receivers in the own-file and package tiers** (`resolver.py:144-150`). Seven C# classes in `namespace Lib` each with `Save()`: `x.Save()` gives 7 edges at 0.14 (PHP `$x->save()` the same). In the tiers loop, when `receiver is not None and len(nodes) > MAX_GUESSES`, return `_Targets()`.
4. **A class-named receiver not in scope falls back to a same-named method in the file** (`resolver.py:140-150`). Inside `class User { static function find() }`, `\Vendor\Lib\Repo::find(1)` resolves to `User.find` at 1.0. When `type_receivers` is set and the receiver looks like a type (contains `\` or `::`, or starts with a capital), skip the own-file and package tiers if `_on_type` finds nothing; let it fall to a name guess.
5. **Ruby's guessed constant for an external `require` overrides internal code** (`structural/ruby.py:41`). Root `util.rb` with `module Util; def self.slug`, and `require 'util'` (no `lib/`): `Util.slug` becomes `::external:util.slug` at 1.0. Only set `binding=_constant(...)` when no repository Ruby file defines that type or container.
6. **Dynamic PHP includes treated as literal paths** (`queries/php/imports.scm:23-29`). `require "$dir/x.php";` gives an IMPORTS edge to root `x.php`. Match double-quoted strings only when they contain no variable.
7. **CMake source-dir variables** (`structural/c.py:28-30`, `136-141`). `${CMAKE_SOURCE_DIR}` and `${PROJECT_SOURCE_DIR}` mean the repository root, not the CMakeLists folder (only `CMAKE_CURRENT_SOURCE_DIR` is relative). Also strip `#` comments before reading (`# include_directories(other)` is read today) and unwrap `$<BUILD_INTERFACE:path>`.
8. **`Context.read` must guard itself** (`structural/context.py`). Resolve the path, require it inside `root.resolve()`, reject absolute paths and `..`, require `is_file()`, cap the size; return None otherwise. Test `../x`, an absolute path and a symlink (skip the symlink test where the OS cannot create one).

## Later

9. Apply `profile.narrow` to `_on_type` results too (no effect today).
10. C#: nested namespaces (`namespace A { namespace B {`) record `package="A"`; join the names. `global using` applies only to its own file; gather them project-wide.
11. PHP: a `require` target ending in `.php` is a path even with backslashes (`__DIR__ . '\lib\x.php'`); compare class names case-insensitively.

Not in this task: C and C++ calls are credited to the module, not the function (an adapter problem in `generic/adapter.py`; noted for the owner).

## Done when

Fixes with tests; the three T17a samples and three T17b samples re-scored, before and after in the pull request; fixture unchanged; `pytest -q` and `ruff check .` pass; explainer updated. Pull request title: `T17f: structural tier review fixes`.
