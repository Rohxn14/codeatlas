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
| Import-scoped (profile) | Java, Go |
| Name guesses only | C, C++, C#, Elixir, Lua, PHP, Ruby, Rust, Scala, Swift |

(T17a and T17b add profiles; update this table when a language gets one.)

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
      class, then the classes around it.
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
- `_signature` (generic adapter) now ends at the header and drops comments, so the `#hash`
  that distinguishes repeated names is identical in the deep and structural tiers and does
  not change when a comment is edited.
