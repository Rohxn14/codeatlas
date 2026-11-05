# T21: Structural adapter scopes: C/C++ callers and C# nested namespaces

> **Reading note.** This brief is history. It is what a cloud session was told to build, kept so you can see what was asked; it is not an instruction for new work.
> - **Built in**: pull request #39 (merged without a review: a good first one to review yourself).
> - **Read first**: `docs/explainers/tags-tier.md` and `docs/explainers/structural-tier.md`, for what was actually built and why.
> - **Code**: `src/codeatlas/indexer/generic/adapter.py`. **Tests**: `tests/indexer/structural/`.
> - **Then** read this brief and its review at the end: the gap between them is where the interesting questions are.
> - Reading order, glossary and how to study a module: `docs/README.md`.

**Wave**: 4 (optional; runs in parallel with T19 and T20; no file overlap)
**Branch**: keep the one the cloud environment gives you

## Goal

Two limits the T17b and T17f reviews traced to the structural (tags) adapter, not to the language profiles:

1. **C and C++ calls are credited to the module, not the function.** Upstream tags queries tag the `function_declarator`, so `_enclosing_key` in `src/codeatlas/indexer/generic/adapter.py` (about line 450) never finds a function around a call. Example: `static int h(void){return 0;} int f(void){ return h(); } int g(void){ return h(); }` gives one `a.c:: -> a.c::h` edge instead of `f -> h` and `g -> h`. The impact engine then cannot tell which function a change reaches.
2. **C# nested namespaces** (`namespace A { namespace B { class C {} } }`) record `package="A"`, because the adapter takes the first `@package.name` capture; `using A.B;` then misses. A second namespace in one file is ignored.

## Plan first, then build

Write `docs/plans/T21.md` (half a page) as your first commit, then keep going: how a definition's span is chosen (the declarator versus the whole `function_definition`), how keys stay stable, and how the C prototype rule changes.

## Files you may create or edit

- `src/codeatlas/indexer/generic/` (the structural adapter)
- `src/codeatlas/indexer/queries/c/`, `cpp/`, `c_sharp/` (extras only; never edit upstream queries)
- `src/codeatlas/indexer/structural/c.py` and `csharp.py`, only where the adapter change requires it (for example `_ends_with_semicolon`, which marks prototypes: once a node spans its body, a later `int x;` must not mark the definition as a prototype)
- `tests/indexer/structural/`, `tests/indexer/generic/` (new files with unique names), `tests/data/structural/c/`, `cpp/`, `csharp/` (relabel the samples' `expected_graph.json` by hand where callers change)
- `docs/plans/T21.md`, `docs/explainers/structural-tier.md`, `docs/explainers/tags-tier.md`

## What to do

1. Make a C or C++ function's node span the whole `function_definition` (body included), so calls inside it get the function as `caller_key`. Do not create a second node for the same function. A declaration without a body stays what it is today.
2. Join nested C# namespace names (`A.B`), and record every namespace a file declares (for example `attrs["packages"]` as a list, with `attrs["package"]` kept as the first, so Java and the C# profile keep working); then let the C# profile reach files by any of their namespaces.
3. Check that no other language changes: run the Java, Go, PHP, Ruby, Rust samples and `python scripts/score_fixture.py` before and after; all identical.

## Measure and done when

In the pull request: the C, C++ and C# samples before and after (calls precision and recall), and one real C repository from `eval/suite/repos.yaml` (shallow clone, at most two attempts) with CALLS whose caller is a module before and after. Tests pass on Linux and Windows CI; `ruff check .` passes; explainer updated. Pull request title: `T21: structural adapter scopes for C, C++ and C#`.

## Review

**Not reviewed yet.** Merged as #39 on Nov 4 without a review. A good first review to do yourself: run the reviewer agent on #39, then read `generic/adapter.py` around `_enclosing_key` and the C/C++ definition spans, and check the C, C++ and C# samples' before-and-after numbers in the pull request. Write the review here.
