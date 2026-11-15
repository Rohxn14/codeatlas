# Checkpoints

One entry per checkpoint of `docs/plans/app-v1.md`, newest first. Each says what was
built, how to see it, what was measured, the weakest points, and the choices the owner
may want to reverse. Written for someone who was not watching the work.

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
