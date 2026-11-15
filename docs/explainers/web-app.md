# The local web app

Modules: `src/codeatlas/web/app.py`, `src/codeatlas/web/overview.py`,
`src/codeatlas/web/confidence.py`, the pages in `src/codeatlas/web/templates/` and the
stylesheet `src/codeatlas/web/static/app.css`. Command: `codeatlas serve` in `cli.py`.

Built in checkpoints (`docs/plans/app-v1.md`). This explainer covers checkpoint 1: the
server and the overview page.

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
| `/s/{slug}/` | The overview of one snapshot |
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

One request for `/s/demo@abc123/`, step by step:

1. uvicorn receives the request and hands it to the FastAPI app made by `create_app`.
2. FastAPI matches the route `/s/{slug}/` and sees that `overview()` asks for a store
   and a snapshot. It calls `get_store`, which opens a `GraphStore` on the database for
   this request only. SQLite connections belong to the thread that opened them, and
   each request runs on a worker thread, so a shared connection would fail.
3. `get_snapshot` calls `find_snapshot(store, "demo@abc123")`. It turns every snapshot
   id in the database into its slug and compares. No match gives a 404 page.
4. `overview()` looks in the `overviews` dictionary. On the first visit it calls
   `build_overview`, which reads the snapshot's nodes, edges, files and raw calls once
   and counts them. A snapshot never changes after it is written, so the result is kept
   for the life of the server.
5. Jinja2 fills `overview.html`. Autoescape is on: a repository named `<img src=x>`
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

- Tests: `tests/web/test_web_app.py` (19 tests): the level boundaries, each counting
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
