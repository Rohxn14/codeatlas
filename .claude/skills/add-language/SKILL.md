---
name: add-language
description: Give a tree-sitter language import-scoped call resolution in CodeAtlas's structural tier. Use when asked to add a language profile (T17a, T17b) or to improve a structural language beyond name guesses.
---

# Add a language to the structural tier

A language gets **definitions and calls** from its tags query (already working for the
twelve structural languages) and **import-scoped resolution** from three small pieces:
an imports query, a resolution profile, and a sample project with hand labels. Go is the
worked example throughout: `queries/go/imports.scm`, `structural/go.py`, `tests/data/structural/go/`.

Rules from `CLAUDE.md` apply: do not edit `models.py` or `indexer/adapter.py`, add no
dependency, no network in unit tests, never skip a failing test, explain every line in the
PR. The resolver (`structural/resolver.py`) is shared; **do not add language names to it**.
If the language needs something the shared code cannot express, say so in the PR.

## Steps

1. **Check the grammar and the tags query.** Run this and read the output:
   ```python
   from codeatlas.indexer.registry import Registry
   r = Registry().adapter_for("<language>").parse("x.<ext>", open("sample").read().encode(), "s@1")
   print(r.tier, [(n.key, n.kind.value) for n in r.nodes], r.calls)
   ```
   Tier must be `structural`. Definitions and calls must show up for functions, methods,
   classes and a call with and without a receiver. If calls are missing (Rust `Point::new()`
   was), add `queries/<language>/extra.scm`; never edit upstream.

2. **Write `queries/<language>/imports.scm`.** Capture names are defined once in
   `queries/README.md`: `@import` (the statement), `@import.target`, `@import.name`,
   `@import.alias`, `@import.wildcard`, `@package.name`. Print the syntax tree of a sample
   (`Parser(...).parse(src).root_node`) to see node types. One pattern per statement shape;
   make sure two patterns cannot match the same statement (a trailing `.` anchor works).
   Test on snippets in `tests/indexer/structural/test_imports_queries.py`: every shape the
   language has, a file with no imports, and the `package` capture.
   Go example: one pattern for `import_spec` with an optional `name:` (alias, `.`, `_`).

3. **Write the profile** in `src/codeatlas/indexer/structural/<language>.py`, a subclass
   of `Profile` (`profile.py`), and add an instance to `PROFILES` in `resolver.py`. It
   answers two questions:
   - `reach(ctx, file, imp) -> Reach`: which repository files does this import reach
     (`paths`), or is it outside the repository (`external`, the name the EXTERNAL node
     will get)? Which qualifier names it in code (`binding`: `fmt` in `fmt.Println`)?
     Does it bring names in unqualified (`names`, `None` for all)? Is it a `*` import
     (`wildcard`)? Use `ctx.by_directory`, `ctx.by_package`, `ctx.by_basename` and
     `ctx.files[path]` (definitions by name, `package` attr). Go reads module paths from
     the Package nodes T15 made: `ctx.index.by_key(file.package_key).attrs["module_path"]`.
   - `package_scope(ctx, file) -> list[str]`: files callable without an import. Go: the
     directory. Java: the same `package`.
   Three class flags adjust the shared rules: `unqualified_is_toplevel` (a bare `F()` is
   never a method), `unqualified_uses_package`, `has_class_chain`. Set what the language
   needs and nothing more.

4. **Write a sample project** in `tests/data/structural/<language>/`: two or three
   packages, an aliased or wildcard import, same-package calls, a test file, one call into
   the standard library. Then `expected_graph.json` in the scorer's format (see
   `eval/fixtures/polyglot_app/expected_graph.json`): nodes from an export, but **edges
   written by hand** from reading the code, including EXTERNAL targets. Generating the
   edges from the resolver's output would test nothing.

5. **Test.** Unit tests for `reach` (one test per import shape, plus external), the
   package scope, and the sample scored with `eval.oracle.score` (see `test_resolver.py`).
   Write down any expected imprecision as an assertion, with the reason.

6. **Score.**
   `python scripts/score_fixture.py` must not regress. Then index two real repositories
   of the language (shallow `git clone`, at most two attempts each) with `build_graph` and
   report: time, CALLS by level, the share of raw calls left unresolved.

7. **Document.** Add the language to the table in `docs/explainers/structural-tier.md`
   (depth: profile or name guess), and mention anything it gets wrong.

8. **Finish.** `ruff check .` and `pytest -q`. Pull request titled with the task id;
   list your open choices under "Questions for the owner".

## Common mistakes

- Matching the same import twice (duplicate `RawImport`s, doubled IMPORTS edges).
- Putting quotes or `.*` into `target`; the adapter wants the bare path or name.
- Treating a test file as part of the importable package (Go `_test.go`).
- Letting a method satisfy a bare function call (Go) or the reverse.
- Hard-coding the module root: monorepos have several (`go.work`), so read it from the
  Package nodes.
- Windows paths: every stored path uses `/`; use `PurePosixPath`, never `os.path`.
