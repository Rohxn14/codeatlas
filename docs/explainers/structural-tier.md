# The structural tier: imports, profiles and the resolver

Modules: `src/codeatlas/indexer/structural/`, `src/codeatlas/indexer/generic/adapter.py`,
`src/codeatlas/indexer/queries/<language>/imports.scm`.
See also `tags-tier.md` (definitions and calls) and `pipeline.md` (where resolvers run).

## What

The tags tier finds definitions and calls in twelve languages, but a call is only a name:
`store.Add(x)`. This tier works out **which definition** it means, for any language that
has three small pieces:

1. a **tags query** (exists for every grammar): definitions and calls;
2. an **imports query** (`queries/<language>/imports.scm`): import statements and the
   file's `package` declarations, turned into `RawImport`s, `attrs["packages"]` (every
   one, nested names joined) and `attrs["package"]` (the first);
3. a **resolution profile** (`structural/<language>.py`): which files an import reaches,
   and which files a file can call into without importing them.

One resolver, `StructuralResolver`, serves all of them. A language with only the tags query
still gets `NAME_GUESS` edges, so every structural language has some CALLS edges.

| Depth | Languages |
| --- | --- |
| Import-scoped (profile) | Java, Go, C#, PHP, Ruby, C, C++, Rust |
| Name guesses only | Elixir, Lua, Scala, Swift |

(Update this table when a language gets a profile.) What each profile maps,
and what it gets wrong:

- **C#** (`structural/csharp.py`). A file belongs to the namespaces it declares, not to its
  folder (the `packages` attribute, file-scoped or block; `namespace A { namespace B {} }`
  is `A.B`, and a file with `namespace A {}` then `namespace B {}` belongs to both). The
  profile keeps its own namespace -> files table, because the context's `by_package` holds
  only the first. `using A.B;` reaches every file of namespace `A.B`; `using static A.B.C;` only the members of class `C`, unqualified;
  `using X = A.B.C;` binds `X` to that class. `Foo.Bar()` with `Foo` a class of the same
  namespace or an imported one looks only at `Foo`'s methods. Wrong: `Console.WriteLine` after
  a bare `using System;` stays unresolved (nothing says `Console` is in `System`); an aliased
  or fully qualified external name is exact; `var x = ...; x.M()` is an untyped receiver
  (up to 5 candidates); a namespace that only wraps others (`A` above) is not recorded, so
  `using A;` does not reach that file.
- **PHP** (`structural/php.py`). `use App\Models\User;` (also `as`, grouped `use App\{A, B}`,
  `use function`) is looked up in the PSR-4 table T15 stored on each Composer Package node
  (`App\` -> `src/` gives `src/Models/User.php`); with no table, a file declaring that
  namespace and class. `require`/`include` with a literal path is a file import (relative
  to the file, then to the repository root). `User::find()` follows the binding;
  `$this->m()`, `self::m()` and `static::m()` stay in the class; a bare `foo()` is a
  function of the same namespace, never a method. Wrong: `parent::m()`, dynamic includes,
  classmap autoloading, magic methods and facades.
- **Ruby** (`structural/ruby.py`). `require_relative "x"` is a path from the file;
  `require "x"` is `lib/x.rb` (the nearest gem's `lib/` if several), else external, with
  the constant guessed from the name (`json` -> `JSON`). Ruby brings no names in, so an
  import reaches files and `Foo.bar` is resolved by the class or module named `Foo` in
  scope. A class or module reopened in several files is one scope. Wrong: a bare word that
  ends a method (`name`) cannot be told from a local variable and is not a call;
  Rails/Zeitwerk autoloading has no `require` to follow, so Rails apps lean on name
  guesses; mixins (`include`) and `method_missing` are not followed.

## Why

- **Three pieces, not an adapter per language.** What differs between languages is small:
  how an import string names files, and what "same package" means. Everything else, the
  order of lookups and the confidence rule, is the same, so it is written once. Rejected:
  a resolver per language (what the deep tier does; accurate but does not scale to "any
  repository"), and type inference (needs a real compiler front end per language).
- **Honest confidence.** A hit in the caller's scope is `IMPORT_SCOPED` with 1 ÷ candidates;
  a repository-wide guess is `NAME_GUESS`, at most 0.3. Nothing found: the call stays raw,
  so the evaluation can count it.
- **Nearest scope wins.** A method in your own class shadows one of the same name
  elsewhere, as in the language. Rejected: the union of all scopes, which would dilute a
  certain answer with unlikely ones.
- **IMPORTS edges go to files, not packages.** The contract allows Module → Module,
  symbol or External, and a Go package is many files. If the importer calls into the
  package, edges go only to the files holding what it calls; otherwise to the first ten
  files by name, 1 ÷ n each. Rejected: one edge per file with no limit (a 200-file package
  would flood the graph), and one arbitrary file (hides the other files from impact analysis).
- **Name-guess cut-off of 5 candidates** (owner's Q2 in `decisions.md` is still open): above
  five, the guess is below 0.17 confidence and mostly noise.
- **Overloads are candidates.** The tags tier keys overloads `Class.m#<hash>`. A `RawCall`
  has no argument types, so the resolver cannot choose and every overload gets 1 ÷ n.

## How

`StructuralResolver.resolve(results, index)`:

1. Build a `Context`: for each file its definitions by name, imports and `package`; lookups
   by directory, package and file name; functions by name per language.
2. For each file, ask its profile for a `Reach` per import, and make a table
   `binding -> Reach`.
3. For each raw call, in order, the first step that finds candidates decides:
   1. *Qualifier is an import binding* (`m.Format`), or a path the profile can follow
      (`profile.qualify`: Rust `crate::util::f()`, `Self::new()`): look only in the reached
      files. An external import gives `::external:<import>.<name>`, confidence 1.0.
   2. *Class chain* (profiles with it: Java `m()` or `this.m()`): methods of the enclosing
      class, then the classes around it. Then, for profiles with `type_receivers`
      (C#, PHP, Ruby): `Foo.bar()` where `Foo` names a class in scope (own file, package
      scope, imported files) looks only at `Foo`'s methods. If the receiver looks like a
      type (`Repo`, `\Vendor\Repo`, `A::B`) but names no class in scope, steps 3 and 4
      are skipped: a same-named method of the caller's own class is not the one meant,
      so the call falls to a name guess (at most 0.3) instead of a 1.0 edge.
   3. *Own file*, then *package scope* (`profile.package_scope`). For a call with a
      receiver, more than 5 candidates in a tier means the receiver's type is unknown:
      the call gets no edge, as a name guess with that many candidates would.
   4. *Files reached by imports*: any member, for a receiver of unknown type; only the
      names the import brings in, for a bare call (Go dot import, Java static import).
   5. Otherwise a **name guess**: functions with that name in the same language, if there
      are 1 to 5.
   At every step the profile may `narrow` the candidates: C++ `ns::f()` drops an `f` of
   another namespace, and a C prototype is swapped for the definition in its source file.
4. Each candidate is a CALLS edge, confidence 1 ÷ candidates (name guesses: at most 0.3).
5. IMPORTS edges: one per reached file (see Why), `STRUCTURAL`; outside the repository
   `::external:<target>`.

**Worked example (Go sample, `tests/data/structural/go`)**: `main.go` imports `fmt`,
`m "example.com/shop/money"` and `example.com/shop/store`; `main` calls `store.New()`,
`s.Add("tea")`, `fmt.Println(m.Format(5))` and `report(s)`.

- The Go profile finds the module path `example.com/shop` on the `go.mod` Package node, so
  `example.com/shop/money` is the directory `money/`, whose only non-test files are
  `money/money.go` and `money/round.go`. The package clause says `money`, but the alias
  binds it as `m`.
- `m.Format`: qualifier `m` is a binding, so look in those files: `money/money.go::Format`,
  one candidate, 1.0. `store.New` likewise reaches `store/store.go::New`.
- `fmt.Println`: `fmt` is under no module path, so it is external:
  `::external:fmt.Println`, 1.0, and `main.go` gets `IMPORTS ::external:fmt`.
- `s.Add`: `s` is a variable, not a binding. Own file: nothing. Package scope (`report.go`):
  nothing. Imported files: `store/store.go` has `Store.Add`, one candidate, 1.0.
- `report(s)`: bare call in Go, so only package-level functions: `report.go::report`.
- IMPORTS: `money` was called into at `Format` only, so one edge to `money/money.go`, not
  to `round.go`.

## C, C++ and Rust (T17b)

Three hooks on `Profile` (all default to doing nothing) carry what these languages need,
so the resolver still names no language:

- `reaches(ctx, file, imp)`: a list of `Reach`es for one statement. Rust
  `use a::{B, c::D as E}` brings names from two files.
- `qualify(ctx, file, call)`: a qualifier that is a written path, not an import binding.
- `narrow(ctx, file, call, nodes)`: drop or swap candidates at each scope step.

`StructuralResolver.set_repo_root()` gives profiles the checkout (`Context.root`,
`Context.read`), as the TypeScript resolver gets it for `tsconfig.json`.

**C and C++** (`structural/c.py`). `queries/c|cpp/extra.scm` add call patterns, which the
upstream tags queries lack, and for C++ tag `namespace ns { }` as a scope, so
`ns::f()` can be checked against `ns.f`. `#include "x.h"` looks beside the including
file, then in `include/` and `src/` of its folder and each ancestor, then in folders named
by `include_directories` / `target_include_directories` in any `CMakeLists.txt` (read as
text, `${CMAKE_CURRENT_SOURCE_DIR}` dropped), then takes the only file anywhere whose path
ends in `x.h`. `#include <x>` (the target keeps its brackets: the grammar has no node
inside them, and they mark the form) only searches include folders, else it is external.
Every header name is usable unqualified (`names=None`). A header and its same-named
source (`x.h` with `x.c`/`x.cpp`, beside it or the only one in the repository) are each
other's package scope. Prototypes: `int f(int);` is tagged as a function just like its
definition. A definition's node spans the whole `function_definition` (see
`tags-tier.md`), so its text ends with `}`; a prototype's node is only the declarator,
and the profile reads the source after it: a `;` before any `{` means no body. (Before
T21 every node was a declarator, and reading on past a body would have found the next
`int x;`.) `narrow` then swaps a prototype
for the same-named definition in its own file or partner source, and drops prototypes
when a definition is among the candidates. The same text gives the qualifier written
before an out-of-line name (`int C::get()` is keyed `get` but belongs to `C`).

Worked example (`tests/data/structural/c`): `src/main.c` has `#include "geometry.h"`.
Not beside it; not in `src/include`, `include`, `src`; `CMakeLists.txt` names
`${CMAKE_CURRENT_SOURCE_DIR}/lib/api`, which holds it: `IMPORTS lib/api/geometry.h`. The
call `area(2.0, 3.0)` finds nothing in `main.c` or its partner (none), then the header's
`area`, a prototype; its partner is `lib/geometry.c` (the only `geometry.c`), whose
`area` has a body: one candidate, `IMPORT_SCOPED`, 1.0.

**Rust** (`structural/rust.py`). The imports query reports each `use` with its `{...}`
items as texts, which the profile expands into leaves; `mod x;` comes with alias `mod`.
A path walks the module tree: `crate` starts at the crate root (the Cargo package's
`library`, else its `entry_points`; the deepest root whose folder holds the file wins, a
library breaking ties; a file directly under `tests/`, `examples/` or `benches/` is its
own root), `self` at the file, `super` at the parent module, a name at a child module
(`x.rs` or `x/mod.rs` in the module's folder) or a workspace crate (`-` and `_` equal).
Segments that name child modules are followed; the first left over is an item. A type
gives a `binding` and `class_name` (`C::new()` looks only at `impl C` methods), a
function gives `names`, an unknown item is looked up among the module's own `pub use`
re-exports (5 hops at most). A path that leaves the repository is external
(`::external:std::collections::HashMap`). Modules get no binding, so a variable
`store.add()` is never taken for `mod store`; `qualify` walks `store::f()` instead.
`Self::f()` and `self.f()` look at the impl type's methods; prelude types (`Vec::new()`)
and unknown lower-case crates (`regex::Regex::new()`) are external.

**Measured** on shallow clones (Linux, this session), share of raw calls left
unresolved, `main` before and this branch after:

| Repository | Files | Before | After | After by level |
| --- | --- | --- | --- | --- |
| `jqlang/jq` (C) | 79 | no calls at all | 34% | 52% scoped, 14% guess |
| `fmtlib/fmt` (C++ and C) | 74 | no calls at all | 57% | 40% scoped, 3% guess |
| `BurntSushi/ripgrep` (Rust) | 102 | 65% | 47% | 45% scoped, 8% guess |

Indexing time went from 0.8 to 2.2 s (jq), 1.8 to 6.0 s (fmt), 1.4 to 1.9 s (ripgrep).
Nearly all of jq's unresolved calls name nothing in the repository (`assert`, `printf`,
macros). fmt's largest gap is `fmt::format(...)` (1,478 calls): fmt opens its namespace
with a macro (`FMT_BEGIN_NAMESPACE`), so no definition carries the `fmt` scope and the
namespace check rejects them all.

**Known wrong or missing**:

- **C and C++ callers in preprocessor-heavy code are still the module.** T21 made a
  function's node span its body, so calls name their function: on jq, CALLS edges went
  from 1,251 (every caller a module) to 3,140 (3,022 with a function caller). The other
  118 sit where tree-sitter cannot form a `function_definition`: `#ifdef` branches inside
  a body (`jv_dtoa.c`, `decNumber.c`) and functions written by macros (`builtin.c`).
- Includes are not transitive: a function declared in a header that is included by an
  included header is a name guess.
- Calls to the C library have no edge: no header in the repository says which names
  `<stdio.h>` declares. Macros, function pointers and calls inside a macro's arguments
  (Rust `println!("{}", f())`) are invisible or unresolved.
- Rust `use super::*` inside `mod tests { }` resolves to the parent of the file, not the
  file: a `RawImport` does not say it sits in an inline module. Own-file lookups come
  first, so calls still resolve; one wrong IMPORTS edge remains (asserted in the tests).
- Rust `use a::f as g;` then `g()` is missed (a `Reach` has no rename); `impl C` in a
  file the import does not reach is missed; trait methods called on a variable are
  ordinary candidates, cut off above 5.
- C++ classes in `.h` files are parsed with the C grammar (the extension table maps `.h`
  to C), so their methods are not seen.

## Review fixes (T17f)

The reviews of T17a and T17b found wrong edges at confidence 1.0, the worst kind for
the impact engine. What changed, and the example each test pins:

- **Rust `narrow`**: in `X::m()` with `X` capitalised, `X` is a type, so only methods
  whose owner is called `X` stay (`Self` is the impl type; a `use a::Item as Product`
  alias is followed to `Item`). Before, `HashMap::new()` beside `impl A { fn new() }`
  gave `A.new` at 1.0; now it gives nothing, and so do `T::new()` and `E::V(1)`.
- **Rust paths stay inside**: `qualify` never makes an external out of `crate::`,
  `self::` or `super::` (even when no crate root is found), or out of `inner::f()` when
  the file holds an inline `mod inner { }` (qualnames starting `inner.`). The last now
  resolves to `inner.f` in the own-file tier.
- **The 5-candidate cut-off** applies in the own-file and package tiers too, not only in
  imported files: seven classes with `Save()` in one C# namespace gave 7 edges at 0.14.
- **Out-of-scope class receivers** (`\Vendor\Lib\Repo::find()` inside `User::find`)
  fall to a name guess (step 3.2 above).
- **Ruby** binds a guessed constant (`require 'util'` -> `Util`) only when no Ruby file
  of the repository defines a class or opens a module of that name.
- **PHP** includes: a double-quoted string counts only when it holds no variable (the
  query anchors `string_content` as the only child), so `require "$dir/x.php"` is no
  longer an import of root `x.php`. A target ending `.php` is a path even with
  backslashes, and class names in `use` compare case-insensitively.
- **CMake**: comments (`#` and `#[[ ]]`) are removed first; `${CMAKE_SOURCE_DIR}` and
  `${PROJECT_SOURCE_DIR}` mean the repository root, `${CMAKE_CURRENT_SOURCE_DIR}` the
  CMakeLists folder; `$<BUILD_INTERFACE:dir>` is `dir`; the first argument of
  `target_include_directories` is a target, not a folder.
- **`Context.read`** guards itself: absolute paths, `..`, a symlink leaving the checkout,
  folders and files over 4 MiB all give None. Paths come from the repository, so a
  crafted repository must not make CodeAtlas read outside it.
- `narrow` now also runs on the class-receiver step (no profile changes it there yet).

**Worked example**: `struct A; impl A { fn new() -> A { A } } fn g() { HashMap::new(); }`.
`qualify`: `HashMap` is no binding, no type of the file, not prelude, and not a module or
crate the walk finds; being capitalised it is not an outside crate either, so no Reach.
Own-file tier: `A.new`. `narrow`: the owner of `A.new` is `A`, not `HashMap`, so it is
dropped; imports and the name guess are narrowed the same way. No edge.

Sample scores were unchanged by these fixes (Java, Go, C#, PHP, Ruby, C, C++, Rust).

## Where

- Input: `ParseResult`s of the structural languages (`calls`, `imports`, module
  `attrs["package"]` and `attrs["packages"]`, `attrs["package_key"]` set by the pipeline)
  and the `SymbolIndex`
  (Package nodes for Go module paths and Cargo crates; `files()` for `CMakeLists.txt`).
- Output: `Edge`s (`CALLS`, `IMPORTS`), with `Resolution.IMPORT_SCOPED`, `NAME_GUESS`,
  `STRUCTURAL`. EXTERNAL nodes are created by the pipeline from `::external:` targets (D-19).
- Registered in `pipeline/plugins.py` as `"structural"`; `languages` is every grammar in
  `GRAMMARS` except the deep ones.
- Adding a language: `.claude/skills/add-language/SKILL.md`. Capture names for imports
  queries: `queries/README.md`.
- `_signature` (generic adapter) now ends at the header and drops comments, and the deep
  Python adapter drops comments inside the header the same way (fixed after review), so
  the `#hash` that distinguishes repeated names is identical in the deep and structural
  tiers and does not change when a comment is edited.
- An untyped receiver (`x.run()`) that matches more than 5 same-named methods in the
  reached files stays raw, like a name guess with that many candidates; a Java static
  import of an outside member (`import static org.junit.Assert.assertEquals`) makes the
  bare call `assertEquals(...)` an external edge.
