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
   file's `package` declaration, turned into `RawImport`s and `attrs["package"]`;
3. a **resolution profile** (`structural/<language>.py`): which files an import reaches,
   and which files a file can call into without importing them.

One resolver, `StructuralResolver`, serves all of them. A language with only the tags query
still gets `NAME_GUESS` edges, so every structural language has some CALLS edges.

| Depth | Languages |
| --- | --- |
| Import-scoped (profile) | Java, Go, C#, PHP, Ruby |
| Name guesses only | C, C++, Elixir, Lua, Rust, Scala, Swift |

(T17b adds profiles; update this table when a language gets one.) What each profile maps,
and what it gets wrong:

- **C#** (`structural/csharp.py`). A file belongs to the namespace it declares, not to its
  folder (the `package` attribute, file-scoped or block). `using A.B;` reaches every file of
  namespace `A.B`; `using static A.B.C;` only the members of class `C`, unqualified;
  `using X = A.B.C;` binds `X` to that class. `Foo.Bar()` with `Foo` a class of the same
  namespace or an imported one looks only at `Foo`'s methods. Wrong: `Console.WriteLine` after
  a bare `using System;` stays unresolved (nothing says `Console` is in `System`); an aliased
  or fully qualified external name is exact; `var x = ...; x.M()` is an untyped receiver
  (up to 5 candidates); only the first namespace of a file is recorded.
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
   1. *Qualifier is an import binding* (`m.Format`): look only in the reached files. An
      external import gives `::external:<import>.<name>`, confidence 1.0.
   2. *Class chain* (profiles with it: Java `m()` or `this.m()`): methods of the enclosing
      class, then the classes around it. Then, for profiles with `type_receivers`
      (C#, PHP, Ruby): `Foo.bar()` where `Foo` names a class in scope (own file, package
      scope, imported files) looks only at `Foo`'s methods.
   3. *Own file*, then *package scope* (`profile.package_scope`).
   4. *Files reached by imports*: any member, for a receiver of unknown type; only the
      names the import brings in, for a bare call (Go dot import, Java static import).
   5. Otherwise a **name guess**: functions with that name in the same language, if there
      are 1 to 5.
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

## Where

- Input: `ParseResult`s of the structural languages (`calls`, `imports`, module
  `attrs["package"]`, `attrs["package_key"]` set by the pipeline) and the `SymbolIndex`
  (Package nodes for Go module paths).
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
