# Tags queries

The structural tier reads each language's tree-sitter **tags query** (`tags.scm`). The
registry looks for it in this order:

1. the `TAGS_QUERY` constant of the grammar's Python package;
2. a `queries/tags.scm` file shipped inside the grammar's wheel (TypeScript, C#, Scala,
   Swift, Elixir);
3. a vendored copy here, at `queries/<language>/tags.scm`.

Every grammar CodeAtlas declares today ships its own query, so nothing is vendored yet.
When a grammar without one is added, copy its upstream `queries/tags.scm` into
`queries/<language>/tags.scm` and add a `LICENSE-NOTICE.md` beside it naming the source
repository, the commit and the licence.

`queries/<language>/extra.scm` holds CodeAtlas's own patterns for gaps in an upstream
query. They are appended to the upstream query, never replacing it:

| File | Adds |
| --- | --- |
| `rust/extra.scm` | path calls such as `Point::new(...)`, which upstream does not tag |

TypeScript and TSX also prepend JavaScript's query, as tree-sitter itself does: the
TypeScript tags file only adds TypeScript-specific patterns (interfaces, signatures).
