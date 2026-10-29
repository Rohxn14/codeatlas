# The structural tags tier

Modules: `src/codeatlas/indexer/generic/` (`grammars.py`, `tags.py`, `text.py`), `src/codeatlas/indexer/registry.py`, `src/codeatlas/indexer/queries/`

## What

One adapter class, `TagsAdapter`, extracts definitions and calls from a file in **any** language that has a tree-sitter grammar and a tags query. It produces the module node first, then a node per function, method, class or interface, and a `RawCall` per call site with the enclosing definition as caller. Twelve grammars are wired in today: Python, JavaScript, TypeScript, TSX, Go, Java, Rust, C#, PHP, C, C++ and Ruby.

The **registry** picks the adapter for each language: a deep adapter if one is registered (T01, T02), else the tags adapter (tier STRUCTURAL), else the text adapter (tier TEXT, module node only). If a grammar package fails to load, the language falls back to text and every result carries the reason in `errors`.

## Why

- **Tags queries instead of hand-written walkers.** GitHub's code navigation uses the same `tags.scm` files, and most grammar packages ship one. A new language is one line in `GRAMMARS` instead of a new adapter. The cost: tags queries only see names, not types or imports, so this tier cannot resolve anything; it records what it saw.
- **Individual grammar packages, not one language pack.** Each `tree-sitter-<lang>` wheel contains a compiled grammar *and* its `queries/tags.scm`, works offline and on Windows, and is maintained by the grammar's authors. `tree-sitter-language-pack` 1.x was rejected: it covers hundreds of languages and includes tags queries, but it downloads each compiled grammar into a user cache on first use, so a fresh CI runner or an offline laptop would need the network to parse, and tests must not use it. The cost of our choice is one dependency line per language.
- **Shipped queries first, then vendored, then small additions.** We read `queries/tags.scm` from the installed package when it exists. The C# package ships none, so the upstream file is vendored unchanged under `indexer/queries/c_sharp/` with a licence notice. Where an upstream query misses calls (C and C++ have no call captures at all; Rust misses `Circle::new()`; C# misses plain `Save()`), a short CodeAtlas `extra.scm` is appended. TypeScript's upstream query only adds to JavaScript's, so TypeScript and TSX load both, JavaScript first.
- **Nesting by byte range.** Tags captures are flat. Sorting definitions by start byte (outermost first) and keeping a stack gives each definition its innermost enclosing definition, from which the qualname (`Outer.inner`), the method owner and a call's caller follow. No language-specific walking needed.
- **Owners written outside the class.** Go (`func (s *Server) Start()`) and Rust (`impl Circle { fn new() }`) put methods outside the type's body, so nesting finds no class. A per-grammar `owner_fields` entry names where the type is written (Go: the method's `receiver`; Rust: the enclosing `impl_item`'s `type`). The qualname becomes `Server.Start`; `owner_key` is set only when that type is defined in the same file, because a key must point at a real node. Otherwise the type name is kept in `attrs["receiver"]` for the resolver.
- **Go types.** Go's query tags every `type X ...` as `@definition.type`. `type_kinds` maps `struct` to CLASS and `interface` to INTERFACE; aliases such as `type ID int` are not nodes.
- **Unique keys.** Java overloads and two Rust `impl` blocks can give the same qualname twice. The second becomes `A.f#2`, so every key in a file is unique. Rejected: adding parameter types to the key, which no structural query can supply reliably for every language.
- **No invented calls.** py-tree-sitter cannot evaluate some predicates, such as Ruby's `(#is-not? local)` that separates method calls from local variables. Any pattern with such a predicate is disabled: fewer calls found, but none made up.
- **Never raise.** tree-sitter tolerates syntax errors, so a broken file still yields what parsed; ERROR and MISSING nodes become messages like `missing ')' at line 7`. Any unexpected failure during extraction is caught and recorded, leaving the module node, so the file is never lost.

## How

`TagsAdapter(spec)` loads the grammar, joins the query parts, compiles the query and disables unsupported patterns. `parse(path, source, snapshot_id)` then:

1. Parses `source` into a tree and runs the query once; each match is a dict from capture name to nodes.
2. **Definitions.** For each match with a `@name` and a `@definition.function|method|class|interface` capture (or a mapped `@definition.type`), keep one definition per name node; if two patterns claim the same name, the smallest captured node wins. `@definition.module` and others (constants, fields, macros) are ignored: the file is the module.
3. **Names.** Walk the definitions outermost first with a stack. With a parent, `qualname = parent.qualname + "." + name`, and a function inside a class or interface gets `owner_key = key(path, parent.qualname)`. Without one, a function may get its owner from `owner_fields`. Repeated qualnames get `#2`, `#3`.
4. **Calls.** For each match with `@reference.call` (or C#'s `@reference.send`) and `@name`: the callee text runs from the start of the call to the end of the name (`s.store.Save`); some queries capture the argument list rather than the call, so its parent is used. `receiver` is everything before the last segment, without the separator (`.`, `::`, `->`). The caller is the innermost definition containing the name, or the module.
5. Collect syntax errors, and return the module node first, then the definitions in source order, and the calls.

**Worked example** (`tests/data/generic/server.go`, abbreviated):

```go
type Store interface { Save(name string) error }
type Server struct { store Store }

func (s *Server) Start() error {
    fmt.Println("starting")
    return s.store.Save("boot")
}
```

| capture | becomes |
| --- | --- |
| `@definition.type` `Store` (interface_type) | INTERFACE `server.go::Store` |
| `@definition.type` `Server` (struct_type) | CLASS `server.go::Server` |
| `@definition.method` `Start` | no enclosing definition; `receiver` field gives `Server`, so FUNCTION `server.go::Server.Start` with `owner_key = server.go::Server` |
| `@reference.call` `Println` | `RawCall(caller_key="server.go::Server.Start", callee_text="fmt.Println", name="Println", receiver="fmt")` |
| `@reference.call` `Save` | `RawCall(..., callee_text="s.store.Save", name="Save", receiver="s.store")` |

## Where

- **Implements** `LanguageAdapter` from `indexer/adapter.py` (`language`, `tier`, `extensions`, `parse`), and produces `ParseResult`, `Node`, `RawCall`, `Span` with `make_key` and `make_node_id` from `models.py`.
- **Registry** (`registry.py`): `DEEP_ADAPTERS` is where T01 and T02 each add one entry; `Registry.adapter_for(language)` and `tier_for(language)` serve discovery and the CLI. Extensions come from discovery's tables.
- **Consumers:** `codeatlas scan` counts its output today. Next, the structural resolver (imports queries and resolution profiles under `indexer/structural/`) turns these raw calls into IMPORT_SCOPED or NAME_GUESS edges, and the pipeline adds CONTAINS edges from `owner_key` and the module node.
- **Known gap:** points are read as `start_point[0]` rather than `.row`, because attribute access on points segfaulted with tree-sitter 0.26.0 in this session.
