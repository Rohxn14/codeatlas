# Wave 2: Monday, Nov 2

**Today**: merge the review-fixes pull request, launch seven cloud sessions at once, and let them run while you are away. **Tonight**: read everything fresh (contract, Wave 1, Wave 2) with your notes, and review the seven pull requests.

## What changed since Day 2's plan

- **Review fixes were done in the review session, not in the old cloud sessions**, as you asked: one commit per issue (#11 to #17), all in one pull request, with tests. Each commit message lists what it changed.
- **The pipeline core exists** (`build_graph`, decision D-21), so nothing in Wave 2 waits for anything else, and all seven sessions run in parallel. T18 is now smaller: the report, the `index`, `view` and `export` commands, and the viewer.
- **Every resolver is pre-registered** in `plugins.py`, so no two sessions edit the same file. Until a resolver merges, its entry shows as "not loaded" in a build's problems, which is true.
- **The three planning tasks no longer stop.** T06, T07 and T16 write `docs/plans/Txx.md` as their first commit and keep going; you read plan and code together tonight.
- **Decisions applied before your review** (each reversible, listed in `docs/decisions.md`): D-11 decorators, D-12 package roles, D-13 problems on module nodes, D-14 nested containment, D-15 and D-16 contract wording, D-17 model size, D-19 external keys; plus D-20 (QA benchmark later, no `run_tests` tool) and D-21 (pipeline core).

## Launch

After merging the "Wave 1 review fixes and Wave 2 readiness" pull request:

```powershell
git switch main; git pull
claude --cloud "Execute docs/tasks/T18-pipeline-and-viewer.md. Follow CLAUDE.md."
claude --cloud "Execute docs/tasks/T06-python-resolver.md. Follow CLAUDE.md."
claude --cloud "Execute docs/tasks/T07-typescript-resolver.md. Follow CLAUDE.md."
claude --cloud "Execute docs/tasks/T16-structural-framework.md. Follow CLAUDE.md."
claude --cloud "Execute docs/tasks/T08-hybrid-search.md. Follow CLAUDE.md."
claude --cloud "Execute docs/tasks/T09-agent-and-mcp.md. Follow CLAUDE.md."
claude --cloud "Execute docs/tasks/T10-eval-harness.md. Follow CLAUDE.md."
```

| Task | Builds | Files it owns | Expect in its pull request |
| --- | --- | --- | --- |
| T18 | Index report, `codeatlas index`, `view`, `export`, HTML viewer | `indexer/pipeline/` (new modules), `view/`, `cli.py` | Screens or output of click indexed and viewed |
| T06 | Python resolver | `languages/python/resolver/` | Fixture and oracle scores for Python |
| T07 | TypeScript and JavaScript resolver | `languages/typescript/resolver/` | Fixture and oracle scores for TypeScript |
| T16 | Structural framework, Java and Go, add-language skill | `indexer/structural/`, `generic/adapter.py`, `queries/java`, `queries/go` | Accuracy on Java and Go samples |
| T08 | Hybrid search | `search/`, two methods in `store/sqlite.py` | A four-configuration table on 15 questions |
| T09 | Agent, 11 tools, MCP server | `agent/` | Five real questions answered with citations |
| T10 | Acceptance suite, co-change benchmark, mutation truth | `eval/suite`, `eval/cochange`, `eval/mutants` | A scoreboard of 5+ repositories, a co-change table, mutation truth |

No two tasks share a file. Merge order tonight does not matter, except that the scores in T06 and T07 only reflect their own resolver until both are merged; run `python scripts/score_fixture.py` after merging both.

## Credit

Wave 1 cost about $2.50 per session; Wave 2 sessions are bigger, so expect $3 to $5 each: about $25 to $35 for all seven, leaving roughly $25 for Wave 3 tomorrow (T11 linker, T12 impact engine, T17a, T14 first scoreboard). Check the balance tonight before launching Wave 3. The credit ends Nov 5, 1:29 PM in Bangalore.

## Tonight: what to read, in order

1. `docs/contract.md`, fresh, end to end. New since you typed it: route and external keys, nested containment, `#` in names, the `role`, `errors` and `skipped_reason` attributes.
2. `docs/decisions.md`: the proposals D-11 to D-21. Write your call next to each; tell me any you want reversed and I will undo the commit.
3. The review sections at the end of each Wave 1 brief, then the fixes pull request's commits, one per issue. Each fix names the file and line the review pointed at.
4. `docs/explainers/pipeline.md`: the piece every Wave 2 task builds on.
5. The Wave 2 briefs, then each Wave 2 pull request with its plan (`docs/plans/T06.md`, `T07.md`, `T16.md`) next to it. For T06 and T07, check that they answered "typed receivers" and the name-guess cut-off the same way.
6. Q1 to Q6 in `docs/decisions.md`. Q2 and Q3 now matter: T06, T07 and T16 used a name-guess cut-off, and T12 will take your answer to Q3.

Write your doubts down as you go; bring them here in one batch.

## Verified before launch

- `pytest -q`: 446 passed (Linux, Python 3.13); `ruff check .` clean.
- `python scripts/score_fixture.py`: CONTAINS 53 of 53 (precision and recall 1.0), TESTS by convention 4 of 19, CALLS 0 (no resolver merged yet). This is the baseline the resolvers improve.
- The SCIP oracle file was regenerated on Linux with the new stable name (`oracle_polyglot_app_061bf641daff.json`): 76 nodes, 43 edges, calls precision 0.953 and recall 0.911 against your labels, as before.
