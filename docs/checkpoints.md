# Checkpoints

One entry per checkpoint of `docs/plans/app-v1.md`, newest first. Each says what was
built, how to see it, what was measured, the weakest points, and the choices the owner
may want to reverse. Written for someone who was not watching the work.

## Checkpoint 5: indexing from the app (Nov 16, 2026)

**Built**

- The start page has a box: type a repository address or a folder, press Index, and
  watch the eight steps of the pipeline tick off. When it is done, one button opens
  the map.
- The list of repositories has "Index again" and "Remove" on each row.
- Addresses on gitlab.com, bitbucket.org and codeberg.org are accepted as well as
  github.com (pull request #49, decision D-36, your choice).
- `codeatlas serve` now starts with no database, and has `--read-only`.

**How to see it**

```powershell
codeatlas serve
```

Try: paste `https://github.com/pallets/click` and press Index. While it runs, open
PitwallOS in another tab: it still answers. Then press "Index again" on PitwallOS
after editing a file, and "Remove" on a repository you do not need.

Then read "Indexing from the app" in `docs/explainers/web-app.md`.

**Measured**

- 14 new tests (96 for the web app); the full suite and `ruff` pass.
- Through the running app: GitLab's `cli` (1,853 files) in 46.1 s, itsdangerous (50
  files) in 1.8 s. The map page of another repository stayed under 0.03 s while the
  large index was writing.

**Weakest points**

- Jobs are kept in memory: stopping the server loses a running index, and there is
  no cancel button.
- Progress has numbers only while files are read. The clone and the resolve step can
  sit for many seconds with nothing moving but the clock.
- A snapshot being indexed again can show an error page until the job ends.
- Old snapshots pile up: indexing a repository whose remote has moved adds a second
  row beside the first.
- A clone is never deleted, so `.codeatlas/repos/` only grows.

**Choices you may want to reverse**

- D-37: one index at a time, in a thread inside the server (the alternative: a
  separate worker program, which survives a restart but is a second thing to run).
- D-38: the home page is always the list, even with one repository (before, one
  repository opened straight away).
- D-39: on any host other than this machine the app is read-only.
- The pipeline functions gained an optional `progress` argument (a shared interface,
  added without changing what existing callers do).

**Next**: checkpoint 6, Ask: the agent in the app, with the first real runs on your
Groq and Gemini keys. Before it, two small changes you approved: the diff reader
counts only lines that really changed, and the text of docs becomes searchable.

## Checkpoint 4: the impact page (Nov 16, 2026)

**Built**

- A third tab, **Impact**: choose a change and see what it touches, which test files
  to run (and how many can be skipped), which other files it reaches, and the path
  behind every row.
- Four ways to choose a change: uncommitted edits, one of the last 15 commits, a
  pasted diff, or "What could a change here break?" on any file or symbol page.
- A bug fix found on the way (pull request #47): the app failed when several requests
  arrived together. 62 of 64 concurrent requests returned an error; now none do.

**How to see it**

```powershell
codeatlas serve        # pick PitwallOS, then the Impact tab
```

Try: click the commit "Qualifying replays from the lake" (7 of 52 test files). Then
edit any line in PitwallOS without committing and click "Check my uncommitted changes".

Then read "The impact page" in `docs/explainers/web-app.md`.

**Measured**

- 19 new tests (82 for the web app); the full suite and `ruff` pass.
- A 20-file commit of PitwallOS answers in 0.44 s. The first impact request for a
  repository also builds the graph: 1.4 s for PitwallOS, 3.7 s for logfire.

**Weakest points**

- Only the indexed commit and uncommitted edits are exact to the line. An older commit
  counts each changed file whole, so its result is too wide.
- The existing diff reader (`impact/diff.py`) counts the three unchanged lines round
  each edit as changed. The page avoids this for git (it asks for no such lines), but
  the command line (`codeatlas impact --git`) and pasted diffs still have it. Fixing
  the reader changes what the measured engine is fed, so it is your decision.
- The trust numbers at the bottom of the page are typed into the template.
- Scores are shown as bare numbers. They are not probabilities, and the page says so,
  but a number still looks more exact than it is.

**Choices you may want to reverse**

- D-35: older commits count whole files (the alternative: follow line numbers through
  later commits).
- Test files reached below 0.3 are counted but not listed.
- Other files are grouped by file with the five strongest symbols each.

**Next**: checkpoint 5, indexing from the app: paste a GitHub address or a folder,
watch progress, and manage the list of repositories.

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
