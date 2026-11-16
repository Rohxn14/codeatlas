# Checkpoints

One entry per checkpoint of `docs/plans/app-v1.md`, newest first. Each says what was
built, how to see it, what was measured, the weakest points, and the choices the owner
may want to reverse. Written for someone who was not watching the work.

## Checkpoint 3: files, symbols and search (Nov 16, 2026)

**Built**

- A file page: the files it uses and is used by, its symbols, its source with line
  numbers. Lines that start a symbol are marked and open the symbol.
- A symbol page: signature, docstring, **used by** and **uses** (each row with how it
  was found and its confidence), the calls that got no edge, the source.
- Search, in the top bar of every page: exact names, whole-word matches in names,
  docstrings and paths, then names that contain the text.
- Links between everything: map to file, arrow to symbol, source line to symbol,
  caller to caller.

**How to see it**

```powershell
codeatlas serve        # pick Antidote graph-hacks
```

Try: click `app/`, click `gate.py`, "Open this file", click `evaluate` in the outline,
then follow one of its callers. Or type `gate` in the search box.

Then read "Files, symbols and search" in `docs/explainers/web-app.md`.

**Measured**

- 17 new tests (62 for the web app); the full suite and `ruff` pass.
- File and search pages answer in about 0.02 s once a snapshot is loaded.

**Weakest points**

- No syntax colouring; the code is plain text.
- Search finds names and docstrings, not code bodies, and has no filters.
- If the checkout changed since it was indexed, source lines can be off by a few
  lines and the page does not say so.
- All of it is still read-only browsing. Impact (checkpoint 4) is the first page that
  answers a question nobody else's tool answers.

**Choices you may want to reverse**

- No syntax colouring, to avoid a new package. `pygments` would do it.
- Search in the app is text only; search by meaning stays on the command line.
- "Used by" is above "Uses" on a symbol page.

**Next**: checkpoint 4, the impact playground: paste a diff or pick a recent commit,
see what it reaches and which tests to run.

## Checkpoint 2: the architecture diagram as the home page (Nov 15, 2026)

**Why it changed shape**

Your review of checkpoint 1: the page "serves no purpose". It was a page of counts,
which is something to check, not something to use. So the diagram is now the first
page of a repository, and the counts moved to a second tab, Coverage.

**Built**

- The map page: one folder drawn as boxes (its folders and files) and arrows (code in
  A uses code in B), laid out in rows with users above what they use.
- Three clicks: a folder opens it; a file keeps only that file's arrows; an arrow
  lists the stored edges behind it, each with how it was found and its confidence.
- Line style is the confidence level (D-33); thickness is the number of edges.
- What is left out is said on the page: hidden arrows, edges that leave the folder,
  boxes with no arrow.
- PitwallOS, Antidote and pydantic/logfire are indexed in the default database.

**How to see it**

```powershell
codeatlas serve        # then pick Antidote graph-hacks
```

Try: click `app/`, then click `gate.py`, then click one of its arrows. At the root,
click the thin arrow from `web/` to `api/`: it is the one HTTP call from the
TypeScript front end to the Python server.

Then read "The architecture diagram" in `docs/explainers/web-app.md`.

**Measured**

- 27 new tests (45 for the web app); the full suite and `ruff` pass.
- First map page: Antidote 0.14 s, PitwallOS 0.25 s, logfire (1,091 files) 0.92 s;
  repeat visits 0.03 s or less.

**Weakest points**

- A file cannot be opened yet. The diagram ends at file boxes; source and symbols are
  checkpoint 3, and until then the map is still not a full tool.
- A long arrow can pass behind a box that lies between its two ends.
- PitwallOS shows four boxes at the root, because all its code is in `src/`.
- The layout is simple: rows are wrapped at six boxes, not balanced, so a folder with
  a long chain of files makes a tall drawing.
- Light mode is still not looked at.

**Choices you may want to reverse**

- D-34: which edge kinds make an arrow; the best-level rule; the cap on drawn arrows.
- No JavaScript: every click loads a page. It is simple and every view has an
  address, but there is no zoom, drag or hover panel.
- `tests/` is drawn like any other folder. It could be hidden by default.

**Next**: checkpoint 3, source and symbols: open a file, see its code, its symbols,
who calls each one, and a search box.

## Checkpoint 1: `codeatlas serve` and the overview page (Nov 15, 2026)

**Built**

- A new command, `codeatlas serve`, and a new package, `src/codeatlas/web/`.
- The overview page for a snapshot: totals, files by tier, edges by confidence level,
  calls that got an edge, languages, packages, and what could not be analysed.
- A list of indexed snapshots, and error pages (404, 503).
- The design basics every later page uses: colour and spacing names in one stylesheet,
  light and dark mode, a layout that works at phone width.
- `GraphStore.snapshots()`, which lists every snapshot in a database.

**How to see it**

```powershell
python -m pip install -e ".[dev]"        # once: adds fastapi, uvicorn, jinja2
codeatlas serve --db .codeatlas/self.db  # this repository's own index
codeatlas serve                          # the default database (the fixture)
```

Then read `docs/explainers/web-app.md`, which follows one request through the code.

**Measured**

- 19 new tests; the full suite and `ruff` pass.
- This repository's index (619 files, 12,493 edges): first page 0.55 s, then cached.
- Looked at in a browser at 1200 and 500 pixels wide, in dark mode.

**Weakest points**

- Not tried on a large repository. The overview reads the whole snapshot into memory.
- Light mode was written but not looked at.
- "61% of calls got an edge" is still the number the product plan calls misleading: it
  mixes calls to built-ins with real gaps. The page says so in words; splitting the
  count by reason (A3) is the real fix.
- The page is facts only. It does not yet say what the repository is for (no README
  text, no entry points).

**Choices you may want to reverse**

- D-30: three new packages, in an optional `[web]` extra (also in `[dev]`, for tests).
- D-33: the three confidence levels and their cut-offs, 0.9 and 0.5.
- The address of a snapshot is `/s/owner~name@sha/`. `~` stands for `/`.
- `census`, `packages` and `problems` in `view/data.py` lost their leading underscore,
  because the web app now uses them too.

**Next**: checkpoint 2, the architecture diagram.

## Checkpoint 0: housekeeping and the plan (Nov 15, 2026)

**Built**

- Two Windows fixes in `indexer/intake.py`, one pull request:
  - A local source is stored as its absolute path, so `impact --git` and the MCP server
    find the checkout from any folder.
  - Clones set `core.longpaths` and retry a refused rename for about five seconds.
- The plan `docs/plans/app-v1.md` and decisions D-29 to D-32.

**How to see it**

```powershell
pytest -q tests/test_intake.py      # 35 tests, 3 of them new
```

**Measured**

- Before: 9 of 47 suite repositories failed on Windows with "Access is denied", and
  microsoft/TypeScript failed on 23 long paths. After: not yet re-run; the full suite
  run is checkpoint 7.

**Weakest points**

- The retry is tested with a fake rename, not with a real program holding a file open.
  Only the suite re-run on Windows shows whether five seconds is enough.
- A real permission problem (a read-only folder) now takes five seconds longer to fail.

**Not code, but needed**

- Three VS Code Java extensions (Gradle for Java, Maven for Java, Oracle Java) build the
  Gradle and Maven projects under `tests/data/` and `.codeatlas/`. That runs build
  scripts from cloned repositories, which this project never does itself. Disable them
  for this workspace: Extensions, search `@installed java`, gear, Disable (Workspace).

**Choices you may want to reverse**

- D-29: the web app before the MCP experiment.
- D-31: the diagram is drawn from the graph only, with our own layout code.
