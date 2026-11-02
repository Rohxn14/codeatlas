# Decision log

Every design decision lands here: the question, the decision, and why. When a pull request asks "Questions for the owner", the answers go here too.

## Decided

| # | Decision | Why | Date |
| --- | --- | --- | --- |
| D-01 | SQLite plus a NetworkX view; no graph database | Nothing to run on Windows or in the cloud VM; you write the traversals yourself | 2026-10-28 |
| D-02 | tree-sitter for every language, including Python | One approach for every language, and it tolerates syntax errors | 2026-10-28 |
| D-03 | Three tiers per file: deep (Python, TS/JS), structural (tags, imports and resolution profiles), text | Coverage everywhere, depth where there is a benchmark | 2026-10-28, renamed 2026-10-29 |
| D-04 | Every edge records how it was resolved and a confidence | Impact ranking and an honest UI both depend on it | 2026-10-28 |
| D-05 | Static analysis only; the eval harness alone runs tests, for pinned benchmark repos | Public repositories are not safe to execute | 2026-10-29 |
| D-06 | Accept a public GitHub URL through a blobless clone, with file, size and time limits | Avoids GitHub API rate limits; keeps history for co-change without old file contents; keeps huge repos from stalling the indexer | 2026-10-29 |
| D-07 | Repository-first: every repository gets a repository layer (packages, tests, co-change) whatever its languages; depth grows per language | The owner's requirement: any public repository must work. "Works" means four promises measured on a suite of about 40 repositories | 2026-10-29 |
| D-08 | Strategy memory moves to the local phase | Frees cloud sessions for the repository layer and more languages; it belongs with AdaptiveAgent anyway | 2026-10-29 |
| D-09 | The MCP server is built with the agent tools in T09 | Same tools, one extra entry point; lets the owner practise giving an agent his own tools | 2026-10-29 |
| D-10 | The SCIP oracle runs on Linux only (cloud sessions, CI or WSL), never on Windows | scip-python crashes on Windows: it builds a RegExp from `path.sep`; the upstream fix (PR #211) was closed unmerged. Patching the installed copy would make the answer key unreproducible | 2026-10-30 |

## Proposed on Oct 30 and Nov 2: confirm when you review

From the Wave 1 reviews and the Wave 2 plan. For each, write "yes", "no" or your change after **Your call**; then move the ones you accept into the Decided table above. Five of them change `docs/contract.md`; that text has been added there (Nov 2), and is repeated under "Contract text" below. None of them changes `models.py`.

| # | Proposal | Why | Affects |
| --- | --- | --- | --- |
| D-11 | A function decorator is a call from the decorated function: `@logged` above `create_user` gives CALLS `create_user → logged` | Python runs `logged(create_user)`, and the impact engine must see that changing a decorator changes every function it wraps. The fixture labels already say so; the T01 adapter does not | T01 (issue #13 part 2), T06 |
| D-12 | Packages get `attrs["role"]`: `package`, `fixture` (under a test or fixture folder) or `vendored` (under `vendor/`, `third_party/`, `node_modules/`); no DEPENDS_ON into vendored packages; summaries count real packages only | Indexing this repository finds 31 packages, 30 of them test fixtures; a committed `vendor/` folder makes a library look internal | T15 (issue #16 part 5) |
| D-13 | Parse problems live on the file's module node: `attrs["errors"]` (list of strings), written by the pipeline from `ParseResult.errors`; a skipped file keeps `attrs["skipped_reason"]` | The no-silent-gaps rule needs a place to record the reason, and the store has none; the module node exists for every file, so no schema change is needed | T18 |
| D-14 | CONTAINS also allows Class → nested class and Function → nested function | The fixture labels contain `logged → logged.wrapper`; the contract's list does not allow it | T18, the contract |
| D-15 | A ROUTE node's key is `{path of the handler's file}::route:{METHOD} {path_pattern}` | The fixture labels use it, and the linker (T11) creates these nodes | T11, the contract |
| D-16 | In a qualname, a `#` right after a `.` is part of a name (`A.#secret`, a TypeScript private member); a `#` after a name is the duplicate-name suffix (`Square.label#98f3`) | Both tiers already produce this; it only needs saying | The contract |
| D-17 | When the configured LLM model is retired, auto-resolution stays within its size (`gpt-oss-20b` never silently becomes `gpt-oss-120b`) | A bigger model has different free-tier limits and cost | T04 (issue #14 part 5) |
| D-18 | Wave 2 changes: a new task T18 (pipeline, `codeatlas index`, `view`, `export`) runs first, and `codeatlas index` moves there from T09; T06, T07 and T16 write a plan and stop for review before building; incremental re-indexing moves to the local phase | Nothing joins the Wave 1 parts yet, the owner cannot see results, and every resolver needs the pipeline to score itself. Re-parsing is cheap (583 files in 5.5 s), so incremental indexing saves little now | Wave 2 briefs |
| D-19 | Something outside the repository has the key `::external:{dotted name}` (empty path, like the implicit package); resolvers return edges to such keys, and the pipeline creates one EXTERNAL node per key | The contract's `Resolver` returns edges only, so resolvers cannot create the EXTERNAL nodes the contract's edge table points at | T18, T06, T07, T16, the contract |

| D-20 | The question-answering benchmark (SWE-QA, CodeRepoQA) moves to after Nov 4; the agent's `run_tests` tool is not built, since the agent never runs repository code | Credit goes to the acceptance suite, co-change and mutation truth, which T12 needs; `run_tests` would break the safety rule | T09, T10 |
| D-21 | The pipeline core (`build_graph`) was built in the review session, with every resolver pre-registered in `plugins.py`, so all of Wave 2 runs in parallel | The resolvers, search, agent and harness all need a pipeline to measure themselves; waiting for T18 would cost a day | T18 (smaller), all of Wave 2 |

**Applied on Nov 2, before your review, so Wave 2 could start**: D-11 (T01 fix), D-12 (T15 fix), D-13, D-14, D-19 (pipeline core), D-15, D-16 (contract text), D-17 (T04 fix), D-21. Each is one commit in the "Wave 1 review fixes" pull request and can be reversed. D-18 and D-20 are plan changes.

**Your call**: D-11: · D-12: · D-13: · D-14: · D-15: · D-16: · D-17: · D-18: · D-19: · D-20: · D-21:

### Contract text (for the decisions you accept)

Section 4, two new rows in the identifiers table:

```markdown
| route key | `{path}::route:{METHOD} {path_pattern}` | `backend/routes.py::route:GET /api/users/{id}` | a ROUTE node; the path is the handler's file |
| external key | `::external:{name}` | `::external:requests.get` | something outside the repository; the pipeline creates its EXTERNAL node from the edges that point at it |
```

Section 4, at the end of the **Qualname** paragraph:

```markdown
A `#` right after a `.` is part of a name (a TypeScript private member, `A.#secret`); a `#` that follows a name starts the duplicate-name suffix (`Square.label#98f3`).
```

Section 5, the CONTAINS row of `EdgeKind`:

```markdown
| `CONTAINS` | `"contains"` | Package → Module; Module → Class, Interface or Function; Class → method or nested class; Function → nested function |
```

Section 6, `Node`, add to the common `attrs` keys:

```markdown
`errors` (list of str: parse problems, on a module node), `skipped_reason` (str: why a file was not parsed, on a module node), `role` (packages: `package`, `fixture` or `vendored`)
```

## Open: Day 1 and 2 questions

Answer in a few sentences each. Wrong answers are fine; unexamined ones are not.

### Q1. Why do nodes have both `key` and `id`?

Explain in one sentence, then name one feature that would break if we stored only `id`.

Your answer:

### Q2. Name guesses across languages (decide before Wave 2)

In Python, `obj.save()` has an unknown type. `save` is defined in two Python classes and one TypeScript class, and the caller's file imports neither Python class's module. How many candidates does the guess get, at which resolution level, and with what confidence? The contract keeps name guesses inside one language: give one real case where a candidate in another language would be the right answer, and say which part of CodeAtlas should catch it instead.

Your answer:

### Q3. Many weak paths vs one path (decide before Wave 3)

The impact engine scores a function by its best path: two hops at 0.9 and 0.5 give 0.45. A function reachable by three separate paths of 0.4 each scores only 0.4. Should more paths raise the score? Write a formula, then one case where your formula gives the wrong answer.

Your answer:

### Q4. When the tests miss a real break

Our impact "truth" is the set of tests that fail after a mutation. What happens to measured precision and recall when a mutation breaks real behaviour but no test notices? What would you record so this neither flatters nor punishes the impact engine?

Your answer:

### Q5. When co-change lies (decide before T12 in Wave 3)

Git history says `a.py` and `b.py` changed together in 30 of the 40 commits that touched `a.py`, a confidence of 0.75. Name two situations where that is not a real dependency, and how you would filter each. Then name one real dependency your filter would wrongly throw away.

Your answer:

### Q6. "Works on any repository" in three numbers

Write the three numbers you would put at the top of the README to show that CodeAtlas works on any repository. Which of the three could look good while the product is actually bad, and what would you pair it with?

Your answer:
