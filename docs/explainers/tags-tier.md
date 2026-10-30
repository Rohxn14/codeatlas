# The structural tags tier

Modules: `src/codeatlas/indexer/generic/adapter.py`, `src/codeatlas/indexer/registry.py`,
`src/codeatlas/indexer/queries/`.

## What

One adapter class, `TagsAdapter`, gives any language with a tree-sitter grammar and a
**tags query** its functions, methods, classes and interfaces as nodes, plus every
name-level call as a `RawCall`. It is constructed per language with that language's
grammar and query. The **registry** decides which adapter each language gets: a deep
adapter if one is registered, otherwise the tags adapter (tier `STRUCTURAL`), otherwise
`TextAdapter` (tier `TEXT`), which emits only the file's module node and the reason.

## Why

- **Tags queries already exist.** GitHub's code navigation uses a `tags.scm` file per
  grammar that marks definitions (`@definition.function`, `@definition.class`, ...) and
  references (`@reference.call`), each with a `@name`. They are maintained upstream, so
  reading them generically covers many languages with no per-language code. Rejected:
  writing a small extractor per language (more accurate, but it does not scale to "any
  repository"), or regular expressions (break on nesting and comments).
- **Individual grammar wheels, not one language pack.** Each `tree-sitter-<lang>` wheel
  ships a compiled grammar and, for all sixteen languages declared, its tags query (as a
  `TAGS_QUERY` constant or a `queries/tags.scm` file), so everything works offline and in
  tests. Rejected: `tree-sitter-language-pack`, whose current versions download grammars
  at run time (network in tests, and a moving target), and which do not bundle the tags
  queries we need.
- **The upstream query is used as shipped.** Gaps are filled by appending
  `queries/<language>/extra.scm` (today only Rust path calls such as `Point::new()`), so
  an upstream improvement is picked up on upgrade.
- **Owners need a little language knowledge.** Java and TypeScript nest methods inside the
  class, so the enclosing class is the owner. Go declares methods at the top level with a
  receiver (`func (s *Server) Handle()`), and Rust inside `impl Point { ... }`. Two small
  tables (`_RECEIVER_FIELDS`, `_IMPL_BLOCKS`) cover those, without a per-language adapter.
- **Never raise.** tree-sitter builds a tree even for broken code, marking `ERROR` and
  `MISSING` nodes. The adapter reports up to 20 of them in `errors` and keeps every
  definition it could still read. Any unexpected exception still returns the module node.
- **Positions are read by index.** `node.start_point[0]` (row) and `[1]` (column), not
  `.row` and `.column`: on tree-sitter 0.26.0 the attribute form crashed the interpreter
  (segmentation fault), which no `try` can catch. Index access works on 0.25 and 0.26,
  so no upper version bound is needed.
- **Filters py-tree-sitter cannot run are switched off, not ignored.** A query can guard a
  pattern with `#is?` / `#is-not?` (Ruby: `(#is-not? local)`, "this identifier is not a
  local variable"). py-tree-sitter does not evaluate those, so the pattern would fire on
  every identifier and report each variable read as a call. The adapter disables any
  pattern that carries one. Today only Ruby's bare-identifier call pattern is affected:
  Ruby loses calls written without arguments or receiver (`helper`), but reports no
  invented ones. Calls with a receiver or arguments (`log.info(x)`, `puts x`) still come
  from the other pattern.
- **Duplicate names get a hash of their signature.** Java overloads share the qualname
  `A.save`; so do `fmt` methods in two Rust `impl` blocks. Numbering them by order (`#2`)
  would change a key whenever an overload is added above another, and keys must survive
  across commits. A short hash of the signature does not depend on order. Rejected: no
  suffix (duplicate node ids in the store) and the full signature in the key (long, and
  full of characters awkward in ids).

## How

`parse(path, source, snapshot_id)`:

1. Emit the module node first: key `path::`, span from line 1 to the last line.
2. Parse; collect syntax errors.
3. Run the tags query once; keep the matches.
4. **Definitions.** For each match with a `definition.<tag>` capture and a `name`:
   `function` and `method` become FUNCTION; `class` CLASS; `interface` INTERFACE; `type`
   becomes CLASS or INTERFACE when the type is a struct or an interface (Go), otherwise it
   is dropped; `module` becomes a *scope* only (it names a qualname prefix but is not a
   node, because the file is the module); every other tag (constants, macros, fields) is
   ignored. A node tagged twice (Rust tags a method as both method and function) is kept
   once, as a method.
5. **Qualnames and owners.** Walk the definitions outer-first. The qualname is the
   enclosing definition's qualname plus `.name`. A function whose direct enclosing
   definition is a class or interface gets that as `owner_key`. A top-level function with a
   Go receiver or inside a Rust `impl` gets `Type.name`, `attrs["receiver"] = "Type"`, and
   an `owner_key` when `Type` is defined in the same file. When several definitions in the
   same scope share a name, every one of them gets `#` plus the first four hex digits of
   the SHA-1 of its signature: `A.save#3f9c`, `A.save#b071`. Only identical signatures
   fall back to order: `A.fmt#c2d4`, `A.fmt#c2d4-2`.
6. **Signature and doc comment.** The signature is the text from the definition's start
   to its body, whitespace collapsed. The doc comment is the run of comment lines directly
   above the definition, with comment markers removed.
7. **Calls.** For each `reference.call` match: the call node is the node spanning both
   the tagged node and the name (Java's query tags the argument list, not the call).
   `callee_text` is the call's text up to the end of the name, whitespace removed; `name`
   is the name; `receiver` is what comes before it, minus one `.`, `?.`, `::` or `->`.
   `caller_key` is the innermost enclosing definition that is a node, else the module key.

Worked example (`tests/data/generic/server.go`, shortened):

```go
type Server struct { store Store }

// Handle saves one user and logs it.
func (s *Server) Handle(name string) error {
	fmt.Println("saving", name)
	return s.store.Save(name)
}
```

| key | kind | owner_key | signature |
| --- | --- | --- | --- |
| `server.go::` | module | | |
| `server.go::Server` | class | | `Server struct` |
| `server.go::Server.Handle` | function | `server.go::Server` | `func (s *Server) Handle(name string) error` |

and two raw calls from `server.go::Server.Handle`: `fmt.Println` (name `Println`, receiver
`fmt`) and `s.store.Save` (name `Save`, receiver `s.store`). Resolving `Save` to a
definition is not this tier's job; it stays a raw call until a resolver handles it.

## Where

- Implements `LanguageAdapter` from `codeatlas.indexer.adapter`; returns `ParseResult` with
  `Node`, `Span` and `RawCall` from `codeatlas.models`, keys and ids from `make_key` and
  `make_node_id`.
- `Registry.adapter_for(language)` is used by `scan` in `cli.py`, and `tier_for` by
  discovery. T01 and T02 add one line each to `DEEP_ADAPTERS`
  (`"python": "module.path:ClassName"`); the deep adapter then wins, and if it fails to
  load the registry falls back to this tier and records why.
- The structural resolver (later, `indexer/structural/`) will turn these raw calls into
  `IMPORT_SCOPED` and `NAME_GUESS` edges; CONTAINS edges come from the pipeline using
  `owner_key` and the module node.
