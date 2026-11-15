# Product plan: from a working engine to a product people use

Written Nov 11, 2026, after a review of the code, the docs, the measured results and one
live run. This is a proposal. Nothing in it is decided; section 6 lists the decisions
that are yours, and every item has an ID so you can answer "B3 yes, G7 no".

## 1. The verdict

CodeAtlas today is a **good engine with no product around it**.

- The engine is real. It indexed `pallets/itsdangerous` from a URL in 5.9 seconds on your
  machine (4.6 of them the clone). 880 tests pass, lint is clean, and the suite has run on
  47 repositories in 38 languages. Every edge says how it was found and how sure it is.
  None of the three projects you named does that last part.
- The product is missing. There is no web app, no "paste a URL" page, no overview of a
  repository, no architecture diagram, no source viewer, no chat. The viewer is one
  static HTML file of tables. The `ask` command has **never produced a documented
  answer**: both recorded attempts died on free-tier rate limits.
- The numbers the README leads with are not yet the numbers a user cares about. "55%
  resolved" is not "55% correct", and precision on real repositories has never been
  measured.

So the work falls into three parts, in this order: **make the map trustworthy and say so
with numbers, make asking actually work, then build the surface people see.** Building the
surface first would put a good-looking page on top of answers nobody has checked.

One more point, about you rather than the code. The learning log is empty, D-11 to D-23
and Q1 to Q6 are unanswered, and T21 is unreviewed. The project's own rule is that you can
explain every line. A plan that adds a web app, a wiki generator and a hosted service on
top of 17,600 lines you have not read yet breaks that rule unless reading is scheduled
into it. Section 7 pairs every phase with the modules to study.

## 2. What I checked, and what I did not

| Checked | Result |
| --- | --- |
| `pytest -q`, `ruff check .` | 880 passed, 3 skipped, 71 s; lint clean |
| `codeatlas index https://github.com/pallets/itsdangerous` | 50 files, 256 nodes, 951 edges, 5.9 s |
| `codeatlas view` on that index | writes a 200 KB page for a 50-file repository |
| MCP server module with the installed `mcp` 2.3 | imports; not exercised with a real client |
| Docs, roadmap, decisions, explainers for agent, search, impact | read in full |
| Code: viewer, agent loop, prompts, MCP server, store schema, intake, LLM config, CLI arguments | read |
| Latest suite results (`suite_20261103_wave3.md`) | read; they predate T20 and T21 |

Not checked: I did not open the viewer in a browser (I read its source). I did not run
`ask` (it needs keys and spends your quota). I did not re-run the suite. I did not read
the resolvers, the structural tier or the eval code line by line. I did not load DeepWiki
or GitDiagram in this session; what I say about them is from memory. Harvest I read from
its README. Hosting limits for Render are from memory and must be confirmed before a
decision rests on them.

## 3. Against the three inspirations

| | DeepWiki | GitDiagram | Harvest (Canonical) | CodeAtlas today |
| --- | --- | --- | --- | --- |
| Paste a URL, get a page | yes | yes | no (CLI ingest) | CLI only |
| Written overview / wiki | yes, model-written | no | yes, per version | none |
| Architecture diagram | yes, model-drawn | yes, model-drawn | symbol graph | neighbourhood graph of one symbol |
| Ask questions | yes, chat | no | yes, streaming, cited | built, never seen working |
| Symbol graph you can explore | no | no | yes | yes, basic |
| Every fact labelled with evidence and confidence | no | no | no | **yes** |
| Change impact and test selection | no | no | no | **yes, measured (F1 0.84)** |
| Says what it could not analyse | no | no | no | **yes** |
| MCP for coding agents | yes | no | none seen | yes, untested with a real client |
| Storage | hosted | hosted | Neo4j | one SQLite file |

Reading of the table: they win on surface, you win on substance. Their diagrams and wikis
are written by a model reading files, so they can be wrong with no sign of it. Yours can
be drawn from edges that each carry evidence. That is the position to build on:

> **The map you can check.** Every arrow shows why it is there and how sure it is; every
> answer cites a line; every gap is listed. And it tells you what your change will break.

Do not try to out-wiki DeepWiki. Match the basics (URL in, overview, diagram, chat) and
win on evidence and impact.

## 4. Who it is for

Three audiences want different things. Trying to serve all three at once is the usual way
a project like this stalls, so the order matters (decision P1).

| Audience | What they want | What it needs from CodeAtlas |
| --- | --- | --- |
| A developer new to a repository | "Show me how this is put together, let me ask" | Web app, overview, diagram, chat |
| A developer using Claude Code | Better answers and fewer wrong edits in a large repo | MCP server that is fast, fresh and small in tokens |
| A team or company | Fewer CI minutes, safer reviews, private code | Impact on pull requests, a GitHub Action, self-hosting, a licence |

My recommendation: **Claude Code users first, the web app second, teams third.** The MCP
path needs the least new code, you plan to test with it anyway, and it forces the engine
to be right before anything is drawn on top of it.

## 5. Every improvement, by area

Size is rough pair-work effort including you understanding it: **S** half a day,
**M** one to three days, **L** about a week, **XL** several weeks. These are estimates,
not measurements.

### A. Trust in the map

The core asset. Everything else inherits its errors.

| ID | Improvement | Why (evidence) | Size |
| --- | --- | --- | --- |
| A1 | Re-run the acceptance suite and commit the results | All quoted numbers predate T20 and T21 | S |
| A2 | Measure precision on two real repositories: hand-label about 200 sampled edges each | Precision is 1.0 only on a fixture written for the tool; this is roadmap Q6 and the biggest unknown | L |
| A3 | Report unresolved calls **by reason** (builtin or stdlib, external package, dynamic receiver, no resolver) | "45% unresolved" mixes harmless and harmful; a call to `len()` is not a gap | M |
| A4 | Fix plain JavaScript | express 87%, lodash 96%, slugify 97% unresolved. JavaScript is the most common language on GitHub | L |
| A5 | Add Kotlin, and decide on Bash, Haskell, Dart, Zig | okhttp has 619 Kotlin files indexed as text; koin 541 | M each |
| A6 | Give Scala, Swift, Lua, Elixir resolution profiles | 61 to 91% unresolved in the suite | M each (the `add-language` skill exists) |
| A7 | Look into the 5,125 files with parse errors | TypeScript 3,858, nlohmann_json 240, linux 855: may be test baselines, may be a grammar problem | M |
| A8 | Framework routes: FastAPI routers, Django `urls.py`, Express routers, Spring annotations, Next.js file routes | The HTTP linker is proven on the fixture only (6 of 6) | L |
| A9 | Interface-typed receivers (the open T20 question) | A contract decision is waiting | M |
| A10 | Detect entry points: `main`, CLI scripts, server start, exported API | An overview and a diagram both need "where does it start" | M |
| A11 | Detect generated and vendored files beyond folder names (headers, lockfiles, minified code) | They inflate counts and pollute search | M |
| A12 | Monorepos: per-package indexing instead of stopping at 20,000 files | TypeScript and linux both stop at the cap | L |
| A13 | Optional precise tier from SCIP indexes when a repository ships one | Compiler-grade edges where available; a design decision, and Linux-only for Python | L |
| A14 | New edge kinds: reads config or env var, ORM model to table, docs page mentions symbol | "What uses this setting" is a common question; each is a contract change | M each |

### B. Architecture and the store

| ID | Improvement | Why (evidence) | Size |
| --- | --- | --- | --- |
| B1 | One service layer (`Atlas`: open, index, search, impact, ask) that the CLI, MCP server and web app all call | Logic lives in `cli.py` (702 lines) and `agent/tools.py` (691); a web app would be a third copy | M |
| B2 | Schema migrations | A version mismatch today says "delete the database and re-index" | M |
| B3 | Incremental re-indexing by file hash | `files.sha256` is already stored. Needed for MCP freshness (E3) | L |
| B4 | Stop loading the whole graph into NetworkX for each query; traverse in SQL or cache per snapshot | django peaked at 328 MB, TypeScript at 470 MB; a small server cannot hold that | L |
| B5 | `search_symbols` reads every node in Python per call; use the name index and FTS | Slow on a 65,000-node snapshot, and the agent calls it first on almost every question | S |
| B6 | Split dependencies into extras: core, `[llm]`, `[embed]`, `[mcp]`, `[web]` | `fastembed`, `groq`, `google-genai` and `mcp` install even for `codeatlas scan` | S |
| B7 | Background jobs with progress for indexing | A web request cannot wait 40 s for django; users need a progress bar | M |
| B8 | Snapshot lifecycle: list, delete, size limits, clean old clones | `.codeatlas/repos` only grows | S |
| B9 | SQLite in WAL mode and one connection per request, once there is a server | Readers must not block on a running index | S |
| B10 | A versioned JSON API schema | The web app, MCP and exports should share one shape | M |

### C. Search

| ID | Improvement | Why (evidence) | Size |
| --- | --- | --- | --- |
| C1 | Fix fusion | Fused recall@5 is 0.600, vectors alone 0.733: the combination is worse than one of its parts | M |
| C2 | Split identifiers for full-text search (`createUser` to `create user`) | BM25 only matches whole tokens today | S |
| C3 | Rank tests lower unless asked for | The click demo's top 8 hits are all tests | S |
| C4 | A search benchmark on real repositories, 50+ questions | 15 fixture questions; one question moves recall by 0.067 | M |
| C5 | Re-run the embedding numbers locally | The cloud run could not download the model | S |
| C6 | Filters: kind, path, language; exact-name lookups skip vectors | A product search box needs them | S |
| C7 | Index text-tier files (README, docs, config) by content | They are nodes with no searchable body | M |

### D. The agent (`ask`)

The largest functional gap. A product whose headline feature is "ask questions" cannot
ship with zero recorded successful answers.

| ID | Improvement | Why (evidence) | Size |
| --- | --- | --- | --- |
| D1 | Get one answer, end to end, and paste it in the README | Both documented runs failed on rate limits | S to M |
| D2 | Cut tokens per step: shorter tool descriptions, drop old tool results, summarise history | The first request is about 3,000 tokens against Groq's 8,000 per minute; the whole conversation is resent each step | M |
| D3 | A provider that is not free tier (decision P4) | Free tiers cannot carry a six-step tool loop | M |
| D4 | Streaming answers and visible tool steps | Every product in section 3 with chat streams | M |
| D5 | Conversations: follow-up questions | `ask` takes one question and exits | M |
| D6 | New tools: `repo_overview`, `read_file` (line range), `grep`, `list_dir` | The agent cannot read a README or a config file; `get_symbol_source` stops at 60 lines | M |
| D7 | Record tool **results** in the trajectory, not only their size | The replay demo cannot show steps it never saved | S |
| D8 | A question-answering benchmark with graded answers | D-20 postponed it; nothing measures answer quality | L |
| D9 | Check that a citation supports the claim, not only that the line exists | A real line can be cited for a false statement | L |
| D10 | Treat repository text as untrusted in prompts | A README can contain instructions aimed at the model | S |
| D11 | Decide the fate of `memory/` | The module is one docstring | S |

### E. MCP for Claude Code

| ID | Improvement | Why (evidence) | Size |
| --- | --- | --- | --- |
| E1 | Pin `mcp>=2` in `pyproject.toml` | The server uses the 2.x API; the file says `>=1.2` | S |
| E2 | A test that starts the server and talks to it over stdio | Only the functions are tested, not the protocol | M |
| E3 | Freshness: detect that the working tree moved past the snapshot, say so in every result, re-index changed files | An agent edits code; a map of yesterday's commit then gives confident wrong answers. This is the main risk of the MCP path | L (needs B3) |
| E4 | `codeatlas init`: index the current folder and write the MCP config | Setup is three manual commands with absolute paths | S |
| E5 | Tools for `index`, `list_snapshots`, and the D6 tools | The agent cannot index or look around | M |
| E6 | Tune tool descriptions and output shape against real Claude Code sessions | Descriptions were written for a small model | M |
| E7 | **The experiment**: the same tasks in Claude Code with and without CodeAtlas; compare correctness, tokens and tool calls | The only honest answer to "does this help an agent?" | L |
| E8 | Package as a Claude Code plugin and list it in MCP directories | Distribution | M |

### F. Impact engine

| ID | Improvement | Why (evidence) | Size |
| --- | --- | --- | --- |
| F1 | Impact v2, your design: combine graph and history (Q3, Q5) | The engine loses to plain git history at recall@10 on click, cobra and express | XL |
| F2 | More mutation benchmarks: 5 to 8 repositories, three languages | Two small benchmarks; the cut-off was tuned on the data it is scored on | L |
| F3 | Handle hubs | The click demo selects 52 of 55 test files, a 5% saving | part of F1 |
| F4 | A GitHub Action: comment on a pull request with what it touches and which tests to run | The clearest thing a team would adopt; turns F1 0.84 into saved CI minutes | L |
| F5 | Ownership: who last changed the affected code, CODEOWNERS | "Who should review this" | M |
| F6 | Flag changes to public API (signature changed, symbol removed) | `compare_symbol_across_snapshots` already has the pieces | M |

### G. The product surface

What "look amazing" means in practice. Today: one HTML file, system font, tables, a
420-pixel graph of one symbol's neighbours, no search box, no source code, no links you
can share. It embeds every node in the page, so it grows with the repository (200 KB for
50 files).

| ID | Improvement | Notes | Size |
| --- | --- | --- | --- |
| G1 | `codeatlas serve`: a local web app on the service layer (B1) | Stack is decision P2. Build local first, host later | L |
| G2 | Landing page: one URL box, example repositories, what makes it different | Also the `github.com` to your-domain URL swap both inspirations use | M |
| G3 | Indexing progress: stages with counts as they happen | The pipeline already times each stage | M |
| G4 | Repository overview: what it is, languages, packages, entry points, a coverage meter (deep, structural, text; resolved; problems) | Facts from the graph; one model-written paragraph, cited | L |
| G5 | **Architecture diagram drawn from the graph**: packages and folders as boxes, arrows from real imports, calls and HTTP links; click an arrow to see the edges behind it | The answer to GitDiagram, without a model guessing. Zoom: package, file, symbol | L |
| G6 | A visual language for confidence: solid for certain, dashed for scoped, dotted for a guess, with the reason on hover | This is the brand. Use it everywhere, the same way | M |
| G7 | Source viewer: highlighted code, click a call to jump, callers and callees beside it | Without code on screen, a map is abstract | L |
| G8 | Search box with keyboard shortcut and filters | Needs C1 to C3 | M |
| G9 | Ask panel: streaming, tool steps shown, citations open the source at the line | Needs D1 to D5 | L |
| G10 | Impact playground: paste a diff or pick a recent commit, see what it reaches on the diagram, get the test list | Nobody else has this page | L |
| G11 | Guided pages ("wiki"): a page per package, written from graph facts, every sentence cited, cached per snapshot | The answer to DeepWiki. Needs a paid model once per snapshot (P4) | XL |
| G12 | "What we could not see": parse errors, text-tier languages, unresolved calls by reason | Honesty as a visible feature, not a footnote | M |
| G13 | Links you can share for every symbol, file, search and impact result | Needed for anyone to pass it on | S with G1 |
| G14 | Design basics: type scale, spacing, colour tokens, dark mode, phone layout, keyboard use, empty and error states | Decide once, apply everywhere | M |
| G15 | Compare two snapshots: what changed in the structure between commits | Uses data you already store | L |
| G16 | Export: diagram as SVG or Mermaid, a README badge | Free distribution | S |

### H. Hosting, safety and operations

| ID | Improvement | Why | Size |
| --- | --- | --- | --- |
| H1 | Decide what the public site lets a visitor do (decision P3) | Your vision ("add any repo, ask the model") conflicts with the current rule in CLAUDE.md that a visitor never triggers a live model call | decision |
| H2 | Limits for a public indexer: files, bytes, seconds, clone size, one job at a time, per-IP rate limit | A free host has little memory and CPU; django needs 328 MB | M |
| H3 | A gallery of pre-built indexes, built in CI | The first visit must be instant and cost nothing | M |
| H4 | Cache by repository and commit | Intake already reuses a clone at the same commit | S |
| H5 | Security review of intake: symlinks leaving the checkout, submodules, LFS, very deep trees, archive bombs | It will clone whatever a stranger types. I did not audit this | M |
| H6 | Dockerfile and a deploy config | Also what a company needs to self-host | M |
| H7 | Logs, error tracking, basic usage counts | You cannot improve what you cannot see | M |
| H8 | A written privacy and data note: public repositories only, what is stored, for how long | Asked for by any business | S |

### I. Engineering hygiene

| ID | Improvement | Why | Size |
| --- | --- | --- | --- |
| I1 | **Add a LICENSE** | There is none, and `pyproject.toml` names none. Legally nobody may use or contribute to the code, and no company will touch it | S (decision P5) |
| I2 | Branch protection on `main` | Already first on your roadmap | S |
| I3 | Coverage in CI; a type checker (pyright or mypy) | Type hints are required but never checked | M |
| I4 | Nightly job: fixture score and suite, results kept | Quality numbers drift silently | M |
| I5 | Dependabot; Python 3.13 in the CI matrix | | S |
| I6 | Releases: version tags, a changelog, publish to PyPI so `pipx install codeatlas` works (check the name is free) | Install is clone-and-pip today | M |
| I7 | CONTRIBUTING, SECURITY.md, issue templates | Expected of any project that wants collaborators | S |
| I8 | Ignore `tests/data/repo/gradle/.gradle/` | It shows as untracked in `git status` | S |
| I9 | Docs drift: the agent explainer still describes the v0 impact tools and a `codeatlas.sqlite` path; the README says no `ask` answer could be pasted | Definition of done says explainers match the code | S |
| I10 | Load `.env` in the CLI, or keep saying no | Keys must be set in the shell by hand today (decision) | S |

### J. What makes a business want to work with you

Not features to build now; conditions to meet over time.

| ID | Condition | Depends on |
| --- | --- | --- |
| J1 | A licence, a security policy, a clear "static only, never runs your code" statement | I1, I7, H8 |
| J2 | Published, reproducible numbers on real repositories, including the bad ones | A1, A2, D8, F2 |
| J3 | Value in their existing workflow: the pull request comment and test selection | F4 |
| J4 | Private repositories: a token or a GitHub App, and self-hosting | H6, a design decision |
| J5 | A stable API and file format they can build on | B10, B2 |
| J6 | Proof it helps coding agents | E7 |
| J7 | A public site that looks cared for | G |

## 6. Decisions that are yours

| # | Question | Options | My recommendation |
| --- | --- | --- | --- |
| P1 | Which audience first? | (a) Claude Code users via MCP, (b) web visitors, (c) teams | **(a)**, then (b), then (c). Least new code, forces the engine to be right, and you test with MCP anyway |
| P2 | Web stack | (a) FastAPI, server-rendered pages, small scripts for the diagram and code view; (b) FastAPI JSON API plus a React app; (c) static site built from indexes | **(a)**. You are learning Python; (b) adds a second language and a build chain you would also have to explain line by line. Choose (b) only if front-end skill is itself a goal. (c) cannot index a pasted URL |
| P3 | What may a public visitor do? | (a) recordings only (the current rule); (b) gallery, plus live indexing of any public repository with strict limits, plus search, diagram and impact live, with `ask` replayed or run on the visitor's own key; (c) fully live with your key | **(b)**. Indexing, search, diagram and impact need no model, so "any repo" works for free. Only chat needs a key, and it should not be yours. This changes a rule in CLAUDE.md, so it needs your yes and an entry in `decisions.md` |
| P4 | Which model runs `ask` and writes the guided pages? | (a) stay on Groq and Gemini free tiers; (b) add one paid provider behind the existing interface; (c) both, free by default | **(c)**. Free tiers have not completed a single documented run. A new provider is a new dependency, so it needs your yes |
| P5 | Licence | MIT, Apache-2.0, AGPL | **Apache-2.0**: permissive, with a patent grant companies look for. This is your call entirely |
| P6 | Diagram and overview: from the graph, or written by a model? | (a) graph only; (b) model only, like the inspirations; (c) graph for structure, model for names and one paragraph | **(c)**. Structure must be checkable; a model is good at naming a group of files |
| P7 | Depth or breadth next? | (a) fix JavaScript and measure precision; (b) add more languages | **(a)**. A wrong map in the most common language costs more than a missing one in a rare language |
| P8 | Hosting | Render free tier, another host, or local-only for now | **Local-only until G1 to G10 work**, then decide with real memory numbers |
| P9 | The pending D-11 to D-23 and Q1 to Q6 | Answer as you study each module, or in one sitting | As you study; Q3 and Q5 before impact v2 |

I will push back once on any of these if I think the choice is wrong, then do what you
decide.

## 7. A proposed order

Each phase ends with something you can run and a number you can quote. Each also names
what you read, so the code and your understanding move together. Durations are guesses.

**Phase 0. Ground truth and housekeeping** (about a week)
I1 licence, I2 branch protection, E1 pin, I8, I9, A1 re-run the suite, B6 extras.
Read: contract, modules 1 to 3. Review T21.
Done when: CI is protected, numbers are current, the repository is legal to use.

**Phase 1. CodeAtlas inside Claude Code** (about two weeks)
E4 `init`, E2 protocol test, B5, D6 and E5 tools, E6 descriptions, then E7 the
with-and-without experiment on three repositories.
Read: modules 6 (store), 13 (search), 14 (agent and MCP).
Done when: you have a table of tasks, with and without CodeAtlas, and you believe it.

**Phase 2. A map you can vouch for** (two to three weeks)
A2 precision on real code, A3 unresolved by reason, A4 JavaScript, C1 to C5 search.
Read: modules 8, 9, 10 (the resolvers).
Done when: the README states precision on real repositories, not only the fixture.

**Phase 3. Asking works** (about two weeks)
D1, D2, P4 and D3, D4, D5, D7, D10, then D8 a small benchmark.
Read: module 12 (LLM layer).
Done when: 20 questions on two repositories run to the end, with a graded score.

**Phase 4. The local web app** (four to six weeks)
B1 service layer, B7 jobs, G1, G14, G6, then G4, G5, G7, G8, G12, G13, then G9 and G10.
Read: modules 7 (pipeline, viewer), 16 (CLI).
Done when: `codeatlas serve` on a repository you do not know lets you understand it in
ten minutes. Test that on a friend.

**Phase 5. Public** (two to three weeks)
P3, H2 to H8, B4, G2, G3, H3 gallery, deploy.
Done when: a stranger pastes a URL and gets a page, and the server survives a large one.

**Phase 6. Impact v2 and the pull request** (four weeks or more)
F2 benchmarks first, then F1 your design, F3, F4 the Action.
Read: module 15, answer Q3 and Q5.
Done when: the engine beats plain history on at least two of the three benchmarks, or
you can explain exactly why it cannot.

**Phase 7. Breadth and collaborators** (ongoing)
A5, A6, A8, A12, G11 guided pages, G15, B3 and E3 if not already done, I6 release, J4.

Two items deserve to move earlier if Phase 1 shows the need: **E3 freshness** (if the
experiment shows stale answers hurting) and **B3 incremental indexing** (which E3 needs).

## 8. Risks

| Risk | What would show it | Response |
| --- | --- | --- |
| The map is less precise on real code than on the fixture | A2 comes back well under 0.9 | Lower the confidences, show guesses as guesses, fix the worst resolver first. Better known in Phase 2 than after launch |
| CodeAtlas does not help Claude Code, which already has grep | E7 shows no gain | Narrow the MCP tools to what grep cannot do: callers across files, HTTP links, impact, test selection |
| Scope: this plan is months of work | Phases slip | Phases 0 to 3 alone make an honest, useful tool. Stop there if needed |
| You fall behind the code | You cannot explain a merged change | The definition of done already forbids this; hold to it even when it is slow |
| A free host cannot run the indexer | Out-of-memory on medium repositories | Gallery plus tight limits; heavier indexing stays local |
| Model cost or limits | `ask` fails for visitors | The visitor's own key, or recordings; never your key on a public server |
| A prompt hidden in a repository steers the model | Odd answers on a crafted repository | D10; tools are read-only, which limits the damage |

## 9. What I would do first, if you agree

Three things, each under a day, none needing a design decision beyond P5:

1. Pick the licence (P5) and add it.
2. Pin `mcp>=2`, set up the MCP server in Claude Code on this repository, and use it for
   an hour. Write down every moment it was slow, wrong or silent. That list is the real
   start of Phase 1.
3. Re-run the suite and replace the stale numbers.

Before any of that, a question an interviewer would ask you about this plan: *the suite
says 45% of calls are unresolved. Is that good or bad, and what would you need to know to
answer?* Section A3 is the hint.
