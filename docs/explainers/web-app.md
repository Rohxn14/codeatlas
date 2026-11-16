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
2. FastAPI matches the route and sees that `coverage()` asks for a loaded snapshot.
   It first calls `get_store`, which opens a `GraphStore` on the database for this
   request only. SQLite connections belong to the thread that opened them, and each
   request runs on a worker thread, so a shared connection would fail.
3. `get_loaded` calls `find_snapshot(store, "demo@abc123")`. It turns every snapshot
   id in the database into its slug and compares. No match gives a 404 page.
4. `get_loaded` then looks in the cache. On the first visit `load_snapshot` reads the
   snapshot's nodes, edges, files and raw calls once. `coverage()` calls
   `build_overview` on them and keeps the result. A snapshot never changes after it is
   written, so both are kept for the life of the server.
5. Jinja2 fills `coverage.html`. Autoescape is on: a repository named `<img src=x>`
   reaches the page as the text `&lt;img src=x&gt;`, never as a tag. Names, paths and
   docstrings come from repositories nobody here wrote, so they are untrusted.
6. When the request ends, `get_store` closes the connection.

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
install command. It listens on `127.0.0.1`, which only this machine can reach.

## Where

- Tests: `tests/web/test_web_app.py` (18 tests): the level boundaries, each counting
  function, the routes, the 404 and 503 pages, escaping of repository text, and the
  command's error when there is no database.
- Measured on Nov 15, 2026, on this repository's own index (619 files, 12,493 edges):
  first overview 0.55 s, repeat visits under 0.01 s (cached).
- Not measured: a large repository. `build_overview` reads every node and edge of the
  snapshot into memory once; on django or TypeScript that will take seconds and
  hundreds of megabytes (product plan B4).
- Known limits:
  - The cache is never cleared. After `codeatlas index --force` on the same commit,
    restart the server.
  - There is no sign-in. `--host 0.0.0.0` would let anyone on the network read the
    index; the default is this machine only.
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
