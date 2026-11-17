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
| D-24 | Audience order: developers using Claude Code (through the MCP server) first, web visitors second, teams later | Least new code, it forces the engine to be right before anything is drawn on top of it, and retrieval and generation are tested through Groq, Gemini and Claude Code's MCP client first | 2026-11-11 |
| D-25 | The web app is FastAPI with server-rendered pages and small scripts for the diagram and code view; no separate front-end app | The owner delegated the choice. One language to learn and explain; a React app adds a second language and a build chain. Adding `fastapi` and its server is still asked for when the web app starts | 2026-11-11 |
| D-26 | A public visitor may run everything that needs no language model, live: index a public repository (within limits), search, the diagram, impact. Chat is shown only as replays of runs recorded locally. Live model access for visitors is a later question, only if the project scales | "Any repository" then works for free, and no key ever sits on a server. Keeps CLAUDE.md's rule that a visitor never triggers a live model call; changes the roadmap's "the server never clones anything on request" | 2026-11-11 |
| D-27 | Locally, the free Groq and Gemini tiers stay the only providers. A reliable paid provider is chosen at the production stage | No new dependency or cost while the agent is still being measured | 2026-11-11 |
| D-28 | The code is licensed under Apache-2.0 (`LICENSE`, the unmodified text from apache.org; `license` in `pyproject.toml`) | Without a licence nobody may use or contribute to the code. Apache-2.0 is permissive and has an explicit patent grant, which companies look for; MIT has none, AGPL would keep most companies away | 2026-11-12 |
| D-29 | The local web app (`codeatlas serve`) is built before the MCP experiment. This changes the order in D-24, not the audiences | On Nov 15 the owner asked for an application he can review. The app and the MCP server read the same store through the same functions, so the work is shared | 2026-11-15 |
| D-30 | New packages `fastapi`, `uvicorn` and `jinja2`, in an optional `[web]` extra | D-25 chose FastAPI. An extra keeps a plain install small; `serve` prints the install command when the extra is missing | 2026-11-15 |
| D-31 | The architecture diagram is drawn from the graph only, with a layered layout written in this repository: no model and no diagram library (P6, option a) | A drawing made from edges can be checked arrow by arrow. A model can name a group of files later, but must not decide structure. A hand-written layout is code the owner can read | 2026-11-15 |
| D-32 | Pages are rendered on the server; scripts are plain JavaScript files with no build step | One language to learn first (D-25) | 2026-11-15 |
| D-33 | The app shows confidence at three levels: certain (0.9 or more, solid), likely (0.5 to 0.9, dashed), guess (under 0.5, dotted). One colour; the pattern carries the meaning. The number stored on an edge is unchanged | 0.9 is the lowest typical confidence of the rule-based resolutions in the contract (`self_method`, `route_exact`); under 0.5 means at best one of more than two candidates. A pattern still reads in greyscale and for colour-blind readers | 2026-11-15 |
| D-34 | The diagram's boxes are folders and files, its arrows are counted from `imports`, `calls`, `inherits` and `calls_http` edges, and an arrow is drawn at the best confidence level behind it. A crowded diagram draws its heaviest arrows (three for every two boxes, at least 12) and says how many are hidden | Every repository has folders; many have no packages. Containment, test conventions and co-change are other relations and would bury the structure. One certain import makes a dependency certain whatever else is behind the arrow, and the list behind the arrow shows the split. Antidote's `app/` has over a hundred real arrows between 25 boxes, which nobody can read | 2026-11-15 |
| D-35 | On the impact page a change is exact to the line only when its line numbers are the snapshot's: the indexed commit, and uncommitted edits (read with `git diff -R HEAD`, so the indexed commit is the new side). An older commit counts each changed file whole, and the page says so. Diffs from git are asked for with no context lines (`-U0`), and git may not fetch missing file contents (`GIT_NO_LAZY_FETCH=1`) | The engine maps changed lines to symbols with the snapshot's line numbers; an older commit's numbers have moved, and a wrong symbol is worse than a wide answer. Context lines made a one-line edit mark the function below it. A page view must never reach the network | 2026-11-16 |
| D-36 | Intake accepts public repositories on four hosts: github.com, gitlab.com, bitbucket.org and codeberg.org. The list is fixed in the code (`HOSTS`), not a setting, and any other address is refused | The owner asked what happens with a different link (Nov 16). All four serve `https://<host>/<owner>/<repo>.git`, so the clone logic is the same. The typed text becomes an argument to `git clone`, so a short fixed list is safer than any URL; a self-hosted server or a GitLab subgroup would need its own decision | 2026-11-16 |
| D-37 | The web app indexes on a background thread inside the server, one repository at a time, with jobs kept in memory. The pipeline functions (`index_repository`, `build_graph`, `parse_source`) take an optional `progress(step, detail)` callback | An index takes up to minutes, too long for one request. SQLite has one writer, so one job at a time. A thread needs no second program to run; the cost is that a restart loses a running job. A callback gives real progress where a timer would guess | 2026-11-16 |
| D-38 | The app's home page is always the list of repositories with the index form; it no longer jumps into the only repository | The form has to live somewhere every visit starts | 2026-11-16 |
| D-39 | Indexing and removing from the app are refused for a form posted from another website (`Origin` check), `serve` answers only to `127.0.0.1` and `localhost`, and on any other `--host` the app is read-only (`--read-only` does the same on purpose) | Indexing reads any folder its user names, so only the person at this machine may ask. The public demo must be read-only | 2026-11-16 |
| D-40 | `parse_diff` marks only lines that changed: added lines, and for a removal with nothing added the line just above it. Unchanged context lines in a hunk are not marked | Context made a one-line edit mark a neighbouring function (seen at checkpoint 4). The owner approved the fix on Nov 16. The engine's measured numbers do not move: the evaluation builds changes from symbol spans, not from diffs | 2026-11-16 |
| D-41 | Documentation files (Markdown, reStructuredText) get one `SECTION` node per heading: key `{path}::section:{title}` (`#2` for a repeated heading), the text under the heading in `docstring` (cut at 4,000 characters, marked `truncated`), the heading level in `attrs`. The file stays at the text tier, and a section's only edge is CONTAINS from its file | A README answers questions the code cannot ("how do I install this?"), and search read no documentation text at all. The owner chose sections as nodes over one text blob per file (a hit can point at lines 40 to 62, not at a whole file) and over a separate table (nodes are already searched, embedded and shown). The owner added `NodeKind.SECTION` on Nov 16. Measured: PitwallOS gets 165 sections in 13 files, CodeAtlas 624 in 87; indexing time does not move | 2026-11-16 |
| D-42 | Code and documentation are two searches, never one mixed list. `GraphStore.search_text` and `HybridSearch.search` leave sections out by default and return only sections with `docs=True`; the search page shows two groups | Measured on the 15 fixture questions: with sections mixed in, fused recall@5 fell from 0.600 to 0.400 and BM25 from 0.267 to 0.200, because the README's prose matched the plain-word questions better than the code it describes. Apart, recall@5 is unchanged in all four configurations. MRR still moves a little (BM25 0.144 to 0.164, fused 0.390 to 0.356) because BM25 word statistics are counted over one shared index. Rejected: one list with sections weighted down (a weight to tune per repository). Claude's choice under the owner's delegation; reversible | 2026-11-16 |
| D-43 | The agent gets a twelfth tool, `search_docs`, and its trajectory keeps each tool's result, not only the size | D-42 keeps documentation out of code search, so without its own tool the agent could never read a README. A replayed demo answer (plan D7) cannot show steps whose results were never saved. A result is at most 4,000 characters, so a 20-step trajectory stays under about 100 KB. Claude's choice under the owner's delegation; reversible | 2026-11-17 |
| D-44 | Ask in the app: whole steps shown by a page that reloads every 2 s (no JavaScript); only a local, writable app may ask (read-only gives 403 and no tab); questions kept in memory, with the trajectory file as the lasting record; one question at a time, at most three waiting; follow-ups decided after real runs | The owner's four answers on Nov 17, each the recommended option in `docs/plans/checkpoint-6-ask.md`. One at a time because the free tiers limit tokens per minute | 2026-11-17 |

D-24 to D-28 come from `docs/plans/product-plan.md` (P1 to P5). Still open from that plan: P7 to P9.
D-29 to D-35 and D-37 to D-39 were taken by Claude under the owner's Nov 15 delegation (`docs/plans/app-v1.md`); each can be reversed at a checkpoint.

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

| D-22 | Typed receivers resolve at `SELF_METHOD` 0.9 in both deep languages: a declared type (`service: UserService`, `new UserApi()`) names the class, and a subclass may still override, so not 1.0. T06 already does this; T07 treats every receiver as unknown until the TypeScript adapter records types | The two resolvers disagree today, so the same code pattern gets different confidences in Python and TypeScript, and the impact engine compares them | T06 (done), T02 and T07 (later) |
| D-23 | TESTS edges keep only direct, self-method and import-scoped links; name guesses (at most 0.3) do not become TESTS edges | On networkx, 15,000 TESTS edges came from guesses, and the impact engine selects tests through TESTS edges | T06, T07, T12 |

**Applied on Nov 2, before your review, so Wave 2 could start**: D-11 (T01 fix), D-12 (T15 fix), D-13, D-14, D-19 (pipeline core), D-15, D-16 (contract text), D-17 (T04 fix), D-21. Each is one commit in the "Wave 1 review fixes" pull request and can be reversed. D-18 and D-20 are plan changes.

**Applied on Nov 3, while you delegated decisions**: D-23 (both deep resolvers drop TESTS edges whose resolution is `name_guess`; one test each). D-22 stays half-applied: T06 does it, T07 waits until the TypeScript adapter records receiver types, which is a post-Nov 5 task. Q2 and Q3 stay open: T12 decides Q3 in its plan with "highest signal" kept as a switch.

**Your call**: D-11: · D-12: · D-13: · D-14: · D-15: · D-16: · D-17: · D-18: · D-19: · D-20: · D-21: · D-22: · D-23:

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
