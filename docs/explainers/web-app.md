# The local web app

Modules: `src/codeatlas/web/app.py`, `src/codeatlas/web/overview.py`,
`src/codeatlas/web/confidence.py`, the pages in `src/codeatlas/web/templates/` and the
stylesheet `src/codeatlas/web/static/app.css`. Command: `codeatlas serve` in `cli.py`.

Built in checkpoints (`docs/plans/app-v1.md`). This explainer covers checkpoint 1 (the
server and the coverage page, first called the overview) and checkpoint 2 (the
architecture diagram) and checkpoint 3 (files, symbols and search), each in its own
section further down.

## What

`codeatlas serve` starts a small web server on your own machine and opens a browser on
it. The server reads one CodeAtlas database and shows each indexed repository as pages.

Terms used below:

- **Web server**: a program that waits for requests such as "give me the page at `/`"
  and answers with HTML. Here it is **uvicorn** running a **FastAPI** app.
- **Route**: one address pattern and the function that answers it. `/s/{slug}/` is a
  route; `overview()` is its function.
- **Template**: an HTML file with holes. **Jinja2** fills the holes with values, such
  as `{{ snapshot.repo }}`.
- **Slug**: a snapshot id made safe for an address. `pallets/itsdangerous@672971d66a2e`
  becomes `pallets~itsdangerous@672971d66a2e`, because `/` separates parts of an address.

Routes so far:

| Address | Shows |
| --- | --- |
| `/` | The overview, when the database holds one snapshot; otherwise the list |
| `/snapshots` | Every indexed snapshot, newest first |
| `/s/{slug}/` | The map of one snapshot: the architecture diagram (checkpoint 2) |
| `/s/{slug}/coverage` | The coverage page described below |
| `/static/app.css` | The stylesheet |

The overview page shows, for one snapshot: totals; files by tier; edges by confidence
level, as a meter and per edge kind; the share of calls that got an edge, with the
warning that resolved is not correct; languages; packages; and what could not be
analysed.

## Why

- **A product needs a surface.** Before this, the only page was `codeatlas view`: one
  HTML file with every node embedded, which grows with the repository and cannot search
  or show source. A server can answer one question at a time from the database.
- **FastAPI with pages rendered on the server** (D-25, D-32): one language to learn and
  explain. No JavaScript build step.
- **Counts, not prose.** Every number on the overview is a count of rows in the
  snapshot. No model writes anything. A reader can check each number against the store.
- **Gaps are on the page, not hidden.** The "What could not be analysed" section is the
  project's "no silent gaps" rule made visible.
- **One way to show confidence** (D-33). `confidence.level()` turns the number on an
  edge into certain (0.9 or more), likely (0.5 to 0.9) or guess (under 0.5). The meter
  draws them solid, dashed and dotted. Later pages reuse the same three levels, so a
  dotted line always means a guess. The number on the edge is not changed.

Rejected:

- **A static page built once** (like `view`): cannot search, show source on demand, or
  run impact on a pasted diff.
- **The standard library's `http.server`**: no new package, but routing, templates,
  escaping and tests would all be hand-written, and it has no path to the streaming the
  Ask page needs.
- **Counting containment edges in the confidence meter**: a file containing its
  functions is always certain, so it would make the map look surer than its calls and
  imports are.

## How

One request for `/s/demo@abc123/coverage`, step by step:

1. uvicorn receives the request and hands it to the FastAPI app made by `create_app`.
2. FastAPI matches the route and runs `coverage()` on a worker thread. It calls
   `get_loaded("demo@abc123")`, which looks in the cache first.
3. On the first visit `get_loaded` calls `open_store`, which opens a `GraphStore` on
   the database, and `find_snapshot(store, "demo@abc123")`. That turns every snapshot
   id in the database into its slug and compares. No match gives a 404 page.
4. `load_snapshot` then reads the snapshot's nodes, edges, files and raw calls once,
   and the connection is closed. `coverage()` calls `build_overview` on them and keeps
   the result. Both are kept in memory until the snapshot is indexed again or removed
   through the app (checkpoint 5).
5. Jinja2 fills `coverage.html`. Autoescape is on: a repository named `<img src=x>`
   reaches the page as the text `&lt;img src=x&gt;`, never as a tag. Names, paths and
   docstrings come from repositories nobody here wrote, so they are untrusted.

**Why each handler opens its own connection.** A SQLite connection belongs to the
thread that opened it, and requests that arrive together run on different worker
threads. The first version asked FastAPI for the connection through a dependency
(`Depends(get_store)`). FastAPI may run a dependency on one thread and the handler on
another, so the handler used a connection it did not open. One person clicking never
saw it, because one request at a time keeps landing on the same thread. Sixteen
requests at once did: 62 of 64 failed with `SQLite objects created in a thread can only
be used in that same thread`. Now a handler opens the store in a `with` block and
closes it itself, all on its own thread; the same 64 requests, and 18 more, all
succeed. `test_many_requests_at_once_each_get_a_page` fails on the old code.

`build_overview` in small steps. Worked example: three edges, `contains` at 1.0,
`calls` at 1.0 and `calls` at 0.2.

- `trust_rows` groups by edge kind: `contains` has 1 certain; `calls` has 1 certain and
  1 guess.
- `trust_total` leaves `contains` out: 2 edges, 1 certain (50%), 1 guess (50%).
- `tier_shares` always returns deep, structural, text in that order, so the meter's
  colours never swap places between repositories.
- `problem_lists` cuts each long list to 25 rows for the page and keeps the full count,
  so the page can say "showing the first 25 of 3,858".
- `census`, `packages` and `problems` are the same functions the `view` page uses
  (`view/data.py`), so both pages count the same way.

The `serve` command (`_run_serve` in `cli.py`) imports the web packages only when it
runs. They are an optional extra, so a missing package gives one clear line with the
install command. It listens on `127.0.0.1`, which only this machine can reach, and it
starts even when there is no database yet, so the first index can be made from the page.

## Where

- Tests: `tests/web/test_web_app.py` (18 tests): the level boundaries, each counting
  function, the routes, the 404 and 503 pages, escaping of repository text, and the
  `serve` command.
- Measured on Nov 15, 2026, on this repository's own index (619 files, 12,493 edges):
  first overview 0.55 s, repeat visits under 0.01 s (cached).
- Not measured: a large repository. `build_overview` reads every node and edge of the
  snapshot into memory once; on django or TypeScript that will take seconds and
  hundreds of megabytes (product plan B4).
- Known limits:
  - The cache is cleared only by the app's own indexing and removing. After
    `codeatlas index --force` in a terminal on the same commit, restart the server.
  - There is no sign-in. `--host 0.0.0.0` lets anyone on the network read the index
    (the app is then read-only); the default is this machine only.
  - The "calls without an edge" count mixes harmless calls (built-ins, outside
    libraries) with real gaps (product plan A3).
- Run it:

```powershell
python -m pip install -e ".[dev]"            # includes the web packages
codeatlas index eval/fixtures/polyglot_app
codeatlas serve                              # opens http://127.0.0.1:8765/
```

## The architecture diagram (checkpoint 2)

Modules: `web/diagram.py` (boxes and arrows), `web/layout.py` (rows and order),
`web/data.py` (a snapshot read once and kept), the page `templates/map.html`.

### What

The map page, `/s/{slug}/`, is now the home of a repository. It draws one folder:

- A **box** is a folder or a file directly inside the folder being looked at (the
  **focus**). At the root of Antidote the boxes are `app/`, `api/`, `web/`, `tests/`.
- An **arrow** from A to B means at least one stored edge of kind `imports`, `calls`,
  `inherits` or `calls_http` goes from a file in A to a file in B.
- The arrow's **thickness** grows with the number of edges behind it. Its **line
  style** is the best confidence level behind it: solid if any edge is certain.
- Clicking a folder opens it (`?focus=app/`). Clicking a file keeps only that file's
  arrows (`?pick=app/gate.py`). Clicking an arrow lists the edges behind it
  (`?src=web/&dst=api/`), surest first, each with how it was found.
- Boxes with no arrow at this level are listed under "Not connected here".

The statistics that were the first page moved to a second tab, Coverage
(`/s/{slug}/coverage`).

### Why

- **The owner's review of checkpoint 1**: a page of counts "serves no purpose". Counts
  are something to check, not something to use. A map is used to see how a repository
  is put together and to move through it, so the diagram became the home page.
- **Drawn from edges, not by a model** (D-31). Every arrow can be opened and checked.
  A diagram a model writes from file names can be wrong with no sign of it.
- **Folders, not packages, are the boxes.** Every repository has folders; many have no
  package manifest, or one package for everything (PitwallOS has one).
- **Our own layout code** (D-31): about 100 lines in `layout.py` that can be read in
  one sitting, instead of a diagram library.
- **Pages rendered on the server, links instead of scripts** (D-32). Opening a folder
  or an arrow is an ordinary link, so every view has an address that can be shared and
  the back button works. There is no JavaScript on the page.

Rejected:

- **Drawing every arrow.** Antidote's `app/` folder has 25 boxes and well over a
  hundred arrows; all real, together unreadable. By default the heaviest are drawn
  (three for every two boxes, at least 12) and the page says how many are hidden (D-34).
- **Arrows at the middle of each side.** They all met at one point and lay on top of
  each other. Each arrow now has its own point on the side (`route_arrows`).
- **Arrows drawn over the boxes.** They crossed the names. Arrows are drawn first and
  boxes on top, so a long arrow passes behind the boxes between its ends.
- **Line style from the average confidence.** One certain import plus forty name
  guesses would read as a guess, though the dependency is certain. The best level is
  used, and the list behind the arrow shows the split.

### How

Worked example: three files and three edges, looking at the root.

```
app/api/users.py  --calls 1.0-->  lib/util.py
app/db.py         --calls 0.2-->  lib/util.py
app/api/users.py  --calls 1.0-->  app/db.py
```

1. `file_links` (once per snapshot, in `load_snapshot`) keeps the edges of the four
   "uses" kinds whose two ends are in different files. An edge to an outside library
   has no file at its far end, so it is not a link.
2. `box_path(path, focus)` names the box a file falls in: its first part below the
   focus. At the root, `app/api/users.py` and `app/db.py` both fall in `app/`.
3. `_arrows` counts links per ordered pair of boxes. `app/ -> lib/` gets 2 edges
   (1 certain, 1 guess). The third edge starts and ends in `app/`, so it draws nothing
   here; it appears after opening `app/`. Links with one end outside the focus are
   counted as "outside" and reported, not drawn.
4. `layered_rows` (`layout.py`) decides the rows:
   - `acyclic_pairs` takes arrows heaviest first and skips any that would close a
     cycle, so the rest can be ordered top to bottom. With `a -> b` at 10 edges and
     `b -> a` at 2, `a` goes above `b` and the lighter arrow points upwards.
   - `assign_layers` puts a box one row below the lowest box that uses it. Boxes that
     nothing uses are in the top row.
   - `order_rows` sorts each row by the average position of each box's neighbours,
     four times, alternating down and up. This is the "barycentre" method; it shortens
     arrows and removes many crossings.
5. `_wrap` splits a row of more than six boxes; `_place` gives each box its x and y.
6. `arrows_to_draw` picks which arrows are drawn: one box's, the heaviest, or all.
7. `route_arrows` gives each arrow its own point on the side of each box it touches,
   ordered by where the other end is, and `curve` joins the two points.
8. `map.html` writes the SVG: arrows first, then boxes. Each is a link.

`arrow_edges` answers a click on an arrow: the links whose two ends fall in the two
boxes, sorted surest first, cut to 200 rows with the total kept.

`web/data.py` holds `Loaded`: one snapshot's nodes, edges, files, raw calls and links,
read on the first request and kept in a dictionary for the life of the server. A lock
stops two requests that arrive together from both reading it.

### Where

- Tests: `tests/web/test_web_diagram.py` (27 tests): each layout step, `box_path`,
  counting arrows, the level rule, the cap, picking a box, the edges behind an arrow,
  and the page itself (boxes, an opened arrow, a missing arrow, a folder, a 404).
- Measured on Nov 15, 2026:

| Repository | Files | First map page | Repeat |
| --- | --- | --- | --- |
| Antidote | 161 | 0.14 s | 0.02 s |
| PitwallOS | 249 | 0.25 s | 0.02 s |
| pydantic/logfire | 1,091 | 0.92 s | 0.03 s |

- Looked at in a browser on Antidote and PitwallOS, dark mode, 1200 and 1400 pixels.
- Known limits:
  - A long arrow can pass behind a box between its ends, which hides part of it.
  - A repository whose code sits in one top folder (PitwallOS: `src/`) shows only a
    few boxes at the root; the structure appears after opening that folder.
  - Rows are only wrapped, not balanced, so a folder with a long chain of files gives
    a tall drawing.
  - Not measured on a very large repository (django, TypeScript): every snapshot
    opened stays in memory.

## Files, symbols and search (checkpoint 3)

Modules: `web/pages.py` (the facts on each page), `web/source.py` (reading source
lines), `web/data.py` (lookups added to `Loaded`), the pages `file.html`,
`symbol.html`, `search.html` and the shared pieces in `_parts.html`.

### What

| Address | Shows |
| --- | --- |
| `/s/{slug}/file?path=app/gate.py` | One file: the files it uses and is used by, the symbols defined in it, its source with line numbers |
| `/s/{slug}/symbol?key=app/gate.py::evaluate` | One symbol: signature, docstring, what uses it, what it uses, the calls that got no edge, its source |
| `/s/{slug}/search?q=gate` | Symbols and files matching a name, a word of a docstring, or a path |

Every page links to the others. On the map, a picked file has "Open this file", and
the edges behind an arrow link to their symbols. On a file page, a highlighted source
line starts a symbol and opens it. On a symbol page, every caller and callee is a link.
The search box is in the top bar of every page of a repository.

Each relation row shows the confidence level as the same solid, dashed or dotted line
the diagram uses, with the number and how the edge was found.

### Why

- **A map that stops at file boxes is not a tool.** The point of the diagram is to get
  to the code; these pages are where the path ends.
- **"Used by" is first on a symbol page.** The question asked most often about a
  function is "who calls this"; "what does it call" can be read from its source.
- **Calls with no edge are listed on the symbol page.** The coverage page gives one
  number for the whole repository; here the reader sees the actual calls and can judge
  each one (a built-in, an outside library, or a real gap).
- **The store holds no source**, so lines are read from the folder that was indexed.
  If that folder is gone or the file changed, the page still shows everything the map
  knows and says why there is no source.

Rejected:

- **Syntax colouring.** It needs a highlighting package (a new dependency) or a
  hand-written tokenizer per language. Left out for now; the lines that start a symbol
  are marked instead, which the map can do for every language.
- **Vector search in the search box.** It needs the embedding model loaded in the
  server (slow start, more memory). Full-text search plus a name-contains pass is
  instant and covers looking something up by name. Search by meaning stays in
  `codeatlas search` and the agent.
- **Reading a path as typed.** The path comes from the address bar. `file_page` only
  accepts a path that is a file of the snapshot, and `read_lines` resolves the path and
  refuses anything outside the checkout, so `../../secret.txt` is a 404.

### How

`load_snapshot` now also builds three lookups, once: `by_key` (key to node),
`out_edges` and `in_edges` (node id to its edges). Without them every symbol page
would scan all edges.

**A file page**, for `app/service.py` in a repository where `Service.save` calls
`helper` in `lib/util.py` and one undefined function:

1. `file_page` finds the file's record. No record means a 404.
2. Symbols are the nodes with that path, sorted by line. `depth` is the number of dots
   in the qualname: `Service` is 0, `Service.save` is 1, which indents the outline.
3. `_neighbours` walks the snapshot's file links (the same ones the diagram uses) and
   counts, per other file, the edges and the best confidence: uses `lib/util.py`,
   1 edge, certain.
4. Raw calls whose caller is in this file are counted: 2 calls, 1 got an edge.
5. `read_lines` returns the lines, or `None` and a sentence saying why not.
6. `starts` maps a line number to the symbol that begins there, so the template can
   mark that line and link it.

**A symbol page**: `symbol_page` looks the key up in `by_key`, takes its edges from
`in_edges` and `out_edges`, keeps the relation kinds (`calls`, `calls_http`, `handles`,
`inherits`, `imports`, `tests`), sorts surest first and cuts at 200 rows with the total
kept. Calls with no edge are the raw calls whose caller is this key and that are not
resolved.

**Search**: the route asks the store for full-text hits (`GraphStore.search_text`:
exact name first, then BM25 over names, signatures, docstrings and paths). `search`
then adds nodes whose name (or path, for a file) merely contains the text, shortest
first, because full-text search matches whole words: `gate` does not find `apply_gate`.

### Where

- Tests: `tests/web/test_web_pages.py` (17 tests): the facts of each page, search
  order, the path guard, a checkout that is gone, a file deleted after indexing, text
  from a repository shown as text.
- Measured on Nov 16, 2026: file page of Antidote's `app/gate.py` (340 lines) 0.22 s
  on first load of the snapshot, 0.02 s after; search on pydantic/logfire (1,091
  files) 0.02 s once the snapshot is loaded.
- Known limits:
  - No syntax colouring.
  - Search does not look inside code bodies and has no filters by kind or folder.
  - A file is cut at 5,000 lines and a symbol at 400, each with a note.
  - The source shown is the checkout as it is now. If it changed since indexing, line
    numbers can be off; the page does not detect that yet.
  - `checkout_root` repeats the rule in `agent/tools.py` (`ToolContext.repo_root`).
    Making the agent call this one is a separate, small refactor.

## The impact page (checkpoint 4)

Files: `web/changes.py` (reading a change), `web/impact_page.py` (the facts for the
template), `templates/impact.html`, three routes in `web/app.py`.

### What

The third tab of a repository answers one question: **if this changes, what could
break, and which tests should I run?** The change can be:

- the uncommitted edits in the checkout;
- one of the last 15 commits;
- a diff pasted into a box;
- one file or one symbol (a link on every file and symbol page).

The page then shows what the change touches, the test files to run with the share that
can be skipped, the other files it reaches, and for every row the path that led there:
`helper ← calls 1.00 ← Service.save` reads "Service.save calls helper". It ends with a
plain statement of what is measured and what is not.

Terms:

- **Diff**: the text git prints for a change. Lines starting with `-` were removed and
  lines starting with `+` were added.
- **Hunk**: one block of a diff. Its header `@@ -7,3 +7,4 @@` says: 3 lines from line 7
  of the old file became 4 lines from line 7 of the new file.
- **Working tree**: the files in the folder as they are now, including edits that are
  not committed.

### Why

- **The engine is not changed.** `impact/engine.py` already ranks targets and tests and
  is measured. The page only chooses the change and arranges the answer. Rejected: a
  second, simpler ranking for the page (two answers to one question).
- **Line numbers must be the snapshot's** (D-35). The engine finds the changed symbol by
  asking which symbol holds line N *in the indexed commit*. A diff gives line numbers of
  its new side. So:
  - the indexed commit itself is exact: its new side is the snapshot;
  - uncommitted edits are read with `git diff -R HEAD`. `-R` swaps the sides, so the
    indexed commit becomes the new side. Without it, three lines added at the top of a
    file would shift every later edit onto the wrong symbol. A test does exactly that;
  - an older commit's line numbers have moved since, and following them through later
    commits is more work than it is worth yet. Each file it changed counts whole, and
    the page says the result is wider than the change.
- **Zero context lines (`-U0`).** Git prints three unchanged lines round each edit, and
  `parse_diff` takes a hunk's whole span as changed. In the first run of the tests a
  one-line edit to `helper` also marked `apply_gate`, three lines below. Asking git for
  no context makes git-sourced changes exact. A pasted diff still has its context
  lines; the page says a neighbouring symbol may be included. Fixing that in
  `parse_diff` would change what the measured engine is fed, so it is the owner's call.
- **git may not fetch.** A clone made by CodeAtlas holds file contents only for the
  indexed commit. Showing a commit's diff needs older contents, and git would quietly
  download them. `GIT_NO_LAZY_FETCH=1` forbids that, because opening a page must not
  reach the network. When the diff cannot be made, the commit's file names are used
  (they need no contents) and the files count whole.
- **A commit id from the address is checked** against `^[0-9a-f]{7,40}$` before git sees
  it, so `--help` never reaches the command line as an option. git is always run as a
  list of arguments, never through a shell.
- **The posted form is read by hand.** FastAPI's form reader needs the package
  `python-multipart`. `urllib.parse.parse_qs` from the standard library does the same
  for one text field. A diff over 2 MB is refused with a 413.
- **Other files are grouped by file.** The engine ranks symbols; 300 rows of symbols are
  unreadable. A file with its five strongest symbols under it is closer to the question
  "what do I need to look at".

### How

One request, `/s/demo@abc/impact?commit=c128126`:

1. `impact_page` loads the snapshot and finds the checkout (`checkout_root`).
2. `commit_changes` checks the id, asks git for the full id and subject, then for the
   diff (the indexed commit) or the file names (an older one), and returns a
   `ChangeSet`: a title, the `Change`s, whether it is exact, and a note for the page.
3. `impact_response` opens the store and builds the engine. The engine's graph is built
   on the first impact request for a snapshot and kept on `Loaded.graph`.
4. `engine.impact(changes)` returns ranked targets and tests; `all_test_files(engine)`
   is every test file, for the skipped share.
5. `impact_view` splits the result: test files at or over the engine's cut-off (0.3),
   the count of weaker ones, and the other targets grouped by file. `_why` turns the
   best evidence of each row into hops, and `_named` looks every key up so the template
   can link it.
6. `impact.html` draws tiles, the warnings, the chips of changed symbols and two tables.

Worked example, the repository in `tests/web/test_web_impact.py`. The indexed commit
changes one line inside `helper` in `lib/util.py`:

- changed: `lib/util.py::helper`;
- `tests/test_util.py` calls `helper`: selected. `tests/test_other.py` does not: left
  out, so "1 of 2 test files, 50% can be skipped";
- `app/service.py` is reached because `Service.save` calls `helper`.

### Where

- Tests: `tests/web/test_web_impact.py` (19 tests): each way of choosing a change,
  commit ids that are not ids, the reversed diff, a checkout that moved on, the facts
  of the page, a pasted diff, the size limit, text from a diff shown as text.
- Measured on Nov 16, 2026, on the owner's machine: a commit of PitwallOS (20 files)
  0.44 s; the first impact request also builds the graph (PitwallOS 1.4 s, logfire
  3.7 s).
- Known limits:
  - An older commit counts whole files, so its result is too wide.
  - A pasted diff is taken to end at the indexed commit; the page cannot check that.
  - The engine is rebuilt on every request (about 0.1 to 0.5 s); only its graph is kept.
  - The numbers under "How far to trust this" are written in the template. They come
    from `docs/explainers/impact.md` and must be changed by hand when re-measured.
  - Untracked files (new files never added to git) are not in `git diff`, so they are
    not part of "uncommitted changes".

## Indexing from the app (checkpoint 5)

Files: `web/jobs.py` (the background jobs), `templates/snapshots.html` (the start
page), `templates/job.html` (progress), `templates/remove.html`, five routes in
`web/app.py`, and a `progress` argument through `indexer/pipeline/`.

### What

The start page (`/`) now does three things without the command line:

- **Index a repository.** Type an address (github.com, gitlab.com, bitbucket.org or
  codeberg.org) or a folder on this machine and press Index.
- **Watch it.** A progress page lists the eight steps of the pipeline, marks the one
  running now, and reloads itself every two seconds. When the index is done it shows
  the counts and a button to open the map.
- **Manage the list.** Each stored snapshot has "Index again" and "Remove".

Terms:

- **Job**: one request to index one source. It has a state: waiting, running, done or
  failed.
- **Background thread**: a second line of work inside the same program. The request
  that starts a job returns at once; the indexing carries on in the thread.
- **Read-only**: the app with indexing and removing switched off. A public demo must
  run this way.

### Why

- **A job, not a long request.** Indexing takes from one second (itsdangerous, 50
  files) to most of a minute (GitLab's `cli`, 1,853 files: 46 s). A browser would show
  a blank, spinning page for that long and give up after a while. So `POST /index`
  only creates the job and answers with the address of its progress page.
- **One index at a time.** Indexing writes to the database, and SQLite allows one
  writer. Two jobs at once would also compete for the processor. A second job waits
  for the first (`Jobs._turn` is a lock the running job holds). Reading is not
  blocked: the store uses SQLite's write-ahead log, so pages keep answering while an
  index writes. Measured: the map page stayed under 0.03 s during the 46 s index.
- **The same source is not queued twice.** Pressing Index twice returns the job that
  is already working on that source.
- **Progress by a callback.** `index_repository`, `build_graph` and `parse_source`
  take an optional `progress(step, detail)` function and call it when a step starts.
  The command line passes nothing, so it behaves as before. The alternative was for
  the web app to guess progress from the clock, which would be a lie.
- **Reloading with a `<meta>` tag, not a script.** The progress page carries
  `<meta http-equiv="refresh" content="2">` while the job is active, and the browser
  asks again by itself. The app still has no JavaScript (D-32).
- **The cache is cleared when a snapshot changes.** Checkpoint 1 kept a snapshot in
  memory for the life of the server. Now a finished job and a removal both call
  `forget(snapshot_id)`, so the next page reads the new data.
  `test_index_again_shows_the_changed_files` fails without that line.
- **Remove asks first, and only touches the database.** `GET .../remove` shows a
  confirmation page; only the `POST` deletes. It removes the snapshot's rows and its
  saved report. It never deletes a folder: not yours, and not the clone CodeAtlas
  made.
- **Three guards on who may change things.** Indexing reads any folder its user
  names, so it must only ever be this machine's user asking.
  1. *A form from another website is refused.* Any web page open in the same browser
     can post a form to `http://127.0.0.1:8765/index`. The browser adds an `Origin`
     header naming the site the form is on; `from_this_app` refuses the post when
     that is not the app's own address.
  2. *A request for another host name is refused.* A website can point its own name
     at `127.0.0.1` to get round guard 1. `serve` therefore only answers to
     `127.0.0.1` and `localhost` (Starlette's `TrustedHostMiddleware`).
  3. *Read-only when it is not this machine.* `codeatlas serve --host 0.0.0.0` lets
     other machines reach the app, so it switches to read-only by itself.
     `--read-only` does the same on purpose.

### How

Indexing `C:\code\demo` from the page:

1. The form posts `source=C:\code\demo` to `/index`. `from_this_app` checks the
   `Origin` header, `posted_form` reads the fields, `can_change` refuses in read-only.
2. `checked_source` strips spaces and quotes, then checks what can be checked without
   doing the work: a URL must parse (`parse_repo_url`), a folder must exist. A bad
   value comes back to the form with the reason and the text still in the box.
3. `jobs.start(source)` makes a `Job` with a random id, starts a thread on
   `Jobs._run`, and returns. The handler answers `303 See Other` to `/jobs/<id>`.
4. In the thread, `_run` takes its turn, sets the state to running and calls
   `run_index`, which calls `index_repository(..., progress=tell)`. Each time the
   pipeline starts a step it calls `tell("parse", "50 of 120 files")`, and the job
   stores the step and the detail.
5. Meanwhile the browser asks for `/jobs/<id>` every two seconds. `Job.steps()` turns
   the stored step into eight rows: done, now or next.
6. When `index_repository` returns, `index_done` calls `forget` for the snapshot and
   the state becomes done. The next reload shows the counts and has no refresh tag.
   If the pipeline never reached its last step (`save`), the commit was already
   stored and nothing ran; the page says "already indexed".
7. A failure anywhere (a clone that fails, a folder that vanished) is caught in
   `_run`: the state becomes failed, the message is kept, and the step it stopped at
   is marked.

### Where

- Tests: `tests/web/test_web_index.py` (12 tests): a job's states and steps, one at
  a time, no double queue, the checks on the form, a whole index through the page,
  "already indexed", index again after an edit, a failed index, removal, read-only,
  and a form posted from another website. Two more in `test_web_app.py` cover
  `serve`: the host check, and read-only on another host. No test uses the network.
- Tried by hand on Nov 16, 2026, on the owner's machine, through the running app:
  `https://gitlab.com/gitlab-org/cli` (1,853 files, 46.1 s) and
  `https://github.com/pallets/itsdangerous` (50 files, 1.8 s), started together; the
  second waited for the first.
- Known limits:
  - Jobs live in memory. Stopping the server forgets them, and an index that was
    running is lost. There is no cancel button.
  - While a snapshot is being indexed again, its pages can show an error or a
    half-written map until the job ends.
  - An index run from the command line while the server is up is not noticed for a
    snapshot already opened: restart the server.
  - Progress inside a step is only shown for "Read each file". The clone and "Connect
    calls and imports" can each take many seconds with no number to show.
  - "Index again" on a URL fetches the newest commit, which makes a second snapshot
    beside the old one. Nothing removes old snapshots for you.
  - Removing a snapshot leaves the clone on disk.
  - There is still no sign-in. The guards above assume one person at one machine.
