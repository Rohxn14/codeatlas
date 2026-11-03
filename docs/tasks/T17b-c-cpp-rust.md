# T17b: C, C++ and Rust through the add-language skill

**Wave**: 3 (optional: launch only if the credit allows; otherwise the owner does it locally)
**Branch**: keep the one the cloud environment gives you

## Goal

Give C, C++ and Rust import-scoped call resolution in the structural tier by following `.claude/skills/add-language/SKILL.md` once per language, fixing the skill where it is unclear. Kotlin, in the original plan, has no grammar in `pyproject.toml`, so it stays out until the owner adds one.

## Plan first, then build

Write `docs/plans/T17b.md` (about one page) as your first commit, then keep going without waiting: per language, the import form, the resolution profile, the scope rules, and what you expect to get wrong.

## Files you may create or edit

- `src/codeatlas/indexer/queries/c/`, `queries/cpp/`, `queries/rust/` (imports queries; tags extras only if needed; `queries/rust/extra.scm` already exists)
- `src/codeatlas/indexer/structural/` (one profile module per language and its registration)
- `.claude/skills/add-language/SKILL.md` (corrections only)
- `tests/indexer/structural/` (new files with unique names), `tests/data/structural/c/`, `cpp/`, `rust/`
- `docs/plans/T17b.md`, `docs/explainers/structural-tier.md`

## The three profiles

- **C and C++**: `#include "x.h"` is relative to the including file, then to include folders (`include/`, `src/`, and folders named in a `CMakeLists.txt` `include_directories` or `target_include_directories` line, read as text); `#include <x>` is external unless such a file exists in an include folder. A header and its same-named source file (`x.h`, `x.c`/`x.cpp`) are one scope for calls. C++ `ns::f()` resolves among definitions in namespace `ns` within the reached files.
- **Rust**: `mod x;` maps to `x.rs` or `x/mod.rs` beside the file; `use crate::a::b::C` walks from the crate root (`src/lib.rs` or `src/main.rs`, from T15's Cargo package `root`); `use super::` and `self::` are relative; another workspace crate's name maps through T15's Cargo packages; anything else is external. `C::new()` resolves among `impl C` methods in the reached files.

Cut-off: 5 candidates, as everywhere.

## Tests, measure, done when

As in T17a: per language a sample with `expected_graph.json` scored with `eval.oracle.score`, imports-query and profile unit tests, one real repository each with the unresolved share before and after, the list of skill changes; tests pass on Linux and Windows CI; the plan is committed.

## Review (Nov 3)

**Verdict**: merged (#31) after I resolved its conflicts with T17a (both kept; hooks `reaches`/`qualify`/`narrow` beside T17a's `type_receivers`/`self_receivers`). Meets "Done when"; fixture unchanged. Must fix: Rust `HashMap::new()` lands on any local `new` at 1.0; `crate::`/`super::`/inline-module paths become 1.0 external edges. Should fix: CMake `${CMAKE_SOURCE_DIR}` read relative to the wrong folder; `Context.read` has no guard of its own. Owner's note: C/C++ calls are credited to the module, not the function (an adapter limitation; a later task). Fixes: `docs/tasks/T17f-structural-fixes.md`.
