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

# Imports queries

`queries/<language>/imports.scm` is optional. When it exists the tags adapter runs it on
every file and turns each match into one `RawImport`. It is CodeAtlas's own file, written
per language (upstream tags queries say nothing about imports).

| Capture | Meaning | Becomes |
| --- | --- | --- |
| `@import` | the whole import statement (or one spec of a group) | `line`, and groups captures into one import |
| `@import.target` | the module or path as written, without quotes | `RawImport.target` |
| `@import.name` | an imported name (repeat for several in one statement) | `names=((name, alias), ...)` |
| `@import.alias` | the alias written for the whole import (Go `f "fmt"`, `.`, `_`) | `RawImport.alias` |
| `@import.wildcard` | a `*` import | `names=(("*", None),)` |
| `@package.name` | the file's package declaration | module node `attrs["package"]` |

Rules: one `@import` per statement or spec, so write a pattern for each shape and keep
them from matching the same statement twice (the Java queries use a trailing `.` anchor
for that). A `@import.wildcard` target is the package or class without `.*`.

| File | Languages |
| --- | --- |
| `java/imports.scm` | `import a.b.C;`, `import a.b.*;`, static imports, `package` |
| `go/imports.scm` | single and grouped imports, aliases, dot and blank imports, `package` |

A language with an imports query also needs a resolution profile in
`codeatlas/indexer/structural/` before its imports mean anything; see
`.claude/skills/add-language/SKILL.md`.
