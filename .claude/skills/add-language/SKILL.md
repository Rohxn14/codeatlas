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
   classes and a call with and without a receiver. If calls are missing (Rust `Point::new()`,
   all of C#, PHP `foo()` and Ruby's bare `validate` were; C and C++ had none at all), add
   `queries/<language>/extra.scm`; never edit upstream. Why calls go missing: the adapter
   reads only `@reference.call` (C# upstream says `@reference.send`), and it drops every
   pattern with a predicate such as `#is-not? local` (Ruby's bare words). Also check what
   the language does with *modules* or *namespaces*: Ruby `module` produces no node, so its
   methods look top-level. Read each call's `caller_key`: it must be the function around
   the call. In C and C++ it is the module, because upstream tags the declarator, not the
   whole function (an adapter problem: report it, do not work around it in the profile).
   And check whether a declaration without a body (a C prototype) becomes a node too.

2. **Write `queries/<language>/imports.scm`.** Capture names are defined once in
   `queries/README.md`: `@import` (the statement), `@import.target`, `@import.name`,
   `@import.alias`, `@import.wildcard`, `@package.name`. Print the syntax tree of a sample
   (`Parser(...).parse(src).root_node`) to see node types. One pattern per statement shape;
   make sure two patterns cannot match the same statement (a trailing `.` anchor works, and
   so does a negated field: `(using_directive !name ...)`). Captures of two patterns whose
   `@import` is the same node are merged into one import, so an overlap duplicates
   captures (the first `@import.target` wins), not imports. Useful query features seen so
   far: an optional capture (`alias: (name)? @import.alias`), `#match?` on a capture, and
   one `@import` per clause for grouped imports (PHP `use A\{B, C}`: target `A`, name `B`).
   If the language's import is an ordinary call (Ruby `require`), capture the method name
   as `@import.name` so the profile can tell `require` from `require_relative`; this is the
   one place `@import.name` is not an imported name. If a shape has no node holding the
   bare path (C `<stdio.h>`), keep the text and say so in the query's comment; the profile
   strips it.
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
   Class flags adjust the shared rules; set what the language needs and nothing more:
   `unqualified_is_toplevel` (a bare `F()` is never a method, so the class chain is also
   skipped for bare calls: PHP), `unqualified_uses_package`, `has_class_chain`,
   `type_receivers` (`Foo.bar()` with `Foo` a class in scope looks only at `Foo`'s methods,
   with no import binding; C#, PHP, Ruby) and `self_receivers` (what means "this object":
   `this`, PHP `$this`/`self`/`static`). Leave `parent`/`super` out unless the language
   resolves inheritance, or `parent::m()` finds the child's own `m`.
   Imports that are file paths (PHP `require`, Ruby `require_relative`) use
   `join_relative(directory, path)` from `profile.py`. A language without import bindings
   (Ruby) returns `binding=None, names=None`: files are reached, nothing is named.
   Three optional hooks, for what `reach` alone cannot say (C, C++ and Rust use them):
   `reaches` (one statement brings several `Reach`es: Rust `use a::{B, c::D}`),
   `qualify` (a path written in the call: `crate::m::f()`, `Self::new()`) and `narrow`
   (drop or swap candidates: C++ namespaces, C prototypes, Rust `X::m()` keeps only
   methods of a type `X`). `qualify` must never turn a path that is certainly inside the
   repository (Rust `crate::`/`self::`/`super::`, an inline module) into an external:
   return None and let the scopes decide. A profile that must read a
   build file or a source as text uses `ctx.read(path)` (the checkout, given by the
   pipeline through `StructuralResolver.set_repo_root`; `None` in unit tests without a
   root, so keep working without it; it refuses paths outside the checkout). A guessed
   binding for an external import (Ruby's constant) must not shadow a name the
   repository defines.

4. **Write a sample project** in `tests/data/structural/<language>/`: two or three
   packages, an aliased or wildcard import, same-package calls, a test file, one call into
   the standard library. Then `expected_graph.json` in the scorer's format (see
   `eval/fixtures/polyglot_app/expected_graph.json`): nodes from an export, but **edges
   written by hand** from reading the code, including EXTERNAL targets. Generating the
   edges from the resolver's output would test nothing. Write the sample, export once to
   see the node keys (duplicate names get `#hash` keys), then write edges as
   `calls|imports <src key> -> <dst key>`; an EXTERNAL node is
   `{"key": "::external:<name>", "kind": "external", "language": ..., "path": ""}`. Label
   the true edges even when you know the resolver misses them (a bare Ruby word that ends a
   method): the test then states the miss. Include two classes with the same method name
   called on an untyped receiver, so the imprecision is written down.

5. **Test.** Unit tests for `reach` (one test per import shape, plus external), the
   package scope, and the sample scored with `eval.oracle.score` (see `tests/indexer/structural/test_structural_resolver.py`). Give every test file a name unique across `tests/`, such as `test_php_profile.py`: pytest imports test files by base name, so two `test_resolver.py` files break the whole suite.
   Write down any expected imprecision as an assertion, with the reason. Add the file
   extension to `_language` in `tests/indexer/structural/helpers.py` if it is missing; its
   `resolve()` only sets Go package keys, so build your own `package_key` when a profile
   reads Package nodes (see `test_php_profile.py`).

6. **Score.**
   `python scripts/score_fixture.py` must not regress. Then index two real repositories
   of the language (shallow `git clone`, at most two attempts each) with `build_graph` and
   report: time, CALLS by level, the share of raw calls left unresolved. Count per raw
   call (wrap `structural.resolver._resolve_call` and record whether it returned edges),
   not from exported edges: the pipeline keeps one edge per (source, target, kind), so many
   calls from one caller to one target count once. For "before", check out the base commit
   with `git worktree add <dir> <sha>` and run the same script with `PYTHONPATH=<dir>/src`.
   Pick small repositories from `eval/suite/repos.yaml`: a medium C# repository took 6 s.

7. **Document.** Add the language to the table in `docs/explainers/structural-tier.md`
   (depth: profile or name guess), and mention anything it gets wrong.

8. **Finish.** `ruff check .` and `pytest -q`. Pull request titled with the task id;
   list your open choices under "Questions for the owner".

## Common mistakes

- Matching the same import twice: captures are merged per `@import` node, so the
  second match adds a second `@import.target` that is silently ignored.
- Putting quotes or `.*` into `target`; the adapter wants the bare path or name.
- Treating a test file as part of the importable package (Go `_test.go`).
- Letting a method satisfy a bare function call (Go) or the reverse.
- Hard-coding the module root: monorepos have several (`go.work`), so read it from the
  Package nodes.
- Windows paths: every stored path uses `/`; use `PurePosixPath`, never `os.path`.
