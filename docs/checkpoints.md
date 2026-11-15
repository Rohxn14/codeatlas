# Checkpoints

One entry per checkpoint of `docs/plans/app-v1.md`, newest first. Each says what was
built, how to see it, what was measured, the weakest points, and the choices the owner
may want to reverse. Written for someone who was not watching the work.

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
