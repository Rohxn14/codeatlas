# Plan: the local web app, version 1

Written Nov 15, 2026. On that day the owner handed Claude the planning, design and build
of the product, asked for an application he can review at the end, and asked for regular
checkpoints. This plan is the order of work. It builds on `product-plan.md` (the IDs
below, such as G5, are from its section 5) and on decisions D-24 to D-28.

## What is being built

`codeatlas serve`: a web app that runs on your own machine and shows one indexed
repository as **a map you can check**. Every arrow says why it is there and how sure it
is, every gap is listed, and a change can be traced to what it may break.

It is local only (decision P8). Nothing is hosted until the local app is good.

## What changed from the product plan

The product plan put Claude Code users first (D-24) and the web app in phase 4. The
owner now wants an application to review, so the web app moves to the front (D-29). The
MCP work is not dropped: the app and the MCP server read the same store through the same
functions, so work on one helps the other.

## Decisions taken here

Each is recorded in `docs/decisions.md` and can be reversed.

| # | Decision | Why |
| --- | --- | --- |
| D-29 | The local web app is built before the MCP experiment | The owner asked for an application to review |
| D-30 | New packages `fastapi`, `uvicorn` and `jinja2`, in an optional `[web]` extra | D-25 chose FastAPI; an extra keeps `codeatlas scan` installs small (B6) |
| D-31 | The architecture diagram is drawn from the graph only, by a layout written in this repository; no model, no diagram library (P6 option a) | A drawing made from edges can be checked. A hand-written layered layout is about 150 lines the owner can read; a library would be a black box |
| D-32 | Pages are rendered on the server; scripts are plain JavaScript files with no build step | One language to learn first (D-25) |

## Checkpoints

Each checkpoint is one pull request, merged when CI is green on Linux and Windows. After
each one the owner gets: what was built, how to open it, what is measured, the weakest
points, and the choices he may want to reverse. `docs/checkpoints.md` keeps that list.

| # | Checkpoint | Plan IDs | The owner can then |
| --- | --- | --- | --- |
| 0 | Housekeeping: both Windows intake fixes merged, this plan | I8, roadmap | run the suite on Windows without clone failures |
| 1 | `codeatlas serve` and the overview page: what the repository is, languages by tier, packages, a coverage meter, what could not be analysed. Design basics: colours, type, dark mode, phone width | G1, G4, G12, G14, part of B1 | open a real page for any indexed repository |
| 2 | The architecture diagram: packages and folders as boxes, arrows from real imports, calls and HTTP links, line style by confidence, click an arrow to see the edges behind it | G5, G6 | see how a repository is put together and check any arrow |
| 3 | Source and symbols: a file page with highlighted code, a symbol page with callers and callees, a search box, links that can be shared | G7, G8, G13, B5 | go from the diagram to the code and back |
| 4 | Impact playground: paste a diff or pick a recent commit, see what it reaches and which tests to run | G10 | try the impact engine without the command line |
| 5 | Index from the app: paste a GitHub URL, watch the stages, land on the overview. A list of indexed repositories | G2, G3, B7, B8 | use the app without the command line at all |
| 6 | Ask: the agent in the app, steps shown, citations open the source. First real runs with the Groq and Gemini keys, and the token cuts they need | D1, D2, D4, D7, G9 | ask a question and check the answer's citations |
| 7 | Review round: the owner's changes, the suite re-run with current numbers, docs brought up to date | A1, I9 | read the whole thing and decide what is next |

The order follows one rule: each page links to the next, so nothing is built that cannot
be reached and checked by clicking.

## Rules kept from CLAUDE.md

- `models.py` and `indexer/adapter.py` are not edited. If a checkpoint needs a change
  there, it stops and asks.
- The app never installs, imports or runs code from an indexed repository.
- No silent gaps: a page that leaves something out says how much and why.
- Tests never call a model or the network. The Ask checkpoint uses recorded answers in
  tests and live keys only in runs marked `live`.
- Every new module gets an explainer; every decision a line in `decisions.md`.

## What is paused, and for how long

The build-along steps (questions before each piece, the learning log after each merge)
are paused at the owner's request until the current model's usage limit is reached. Then
he reads, fills in the learning log and reviews. To make that reading possible, each
checkpoint leaves an explainer and a checkpoint note written for someone who was not
watching.

## Risks

| Risk | Sign | Response |
| --- | --- | --- |
| The diagram is unreadable on a large repository | More than about 40 boxes on screen | Start at package level, open one box at a time, cap arrows by weight and say how many are hidden |
| Loading the whole graph per request is slow (B4) | A page takes over a second on django | Cache per snapshot inside the server process; measure first |
| The free model tiers cannot finish an answer (seen twice before) | Rate-limit errors at checkpoint 6 | Cut tokens per step (D2), then report honestly what the free tiers can and cannot do |
| The owner falls behind the code | He cannot explain a merged page | Checkpoint notes and explainers; the review round is his |
