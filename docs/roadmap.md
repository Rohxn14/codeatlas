# Roadmap: where CodeAtlas stands and what comes next

Written Nov 5, 2026, when the project moved from cloud sessions to local, hands-on work.
Update this page as things change; it replaces the day and wave plans in `history/`.

## Where it stands

Every part of the architecture exists, works on real repositories and is measured. That
is v1 at about 90%.

| Part | State |
| --- | --- |
| Indexer, repository layer, three tiers | Working on all 47 suite repositories, 38 languages |
| Resolution | Deep: Python, TypeScript/JavaScript (typed receivers in both). Profiles: Java, Go, C#, PHP, Ruby, C, C++, Rust. Name guesses: the rest |
| HTTP linker | 6 of 6 client calls and 3 of 3 routes on the fixture |
| Store, search, agent, MCP server | Working; `ask` needs an LLM key |
| Impact engine | Test selection F1 0.84 on both benchmarks, skipping 46-64% of test files; does not beat plain git history at predicting co-changing files |
| Command line | `scan`, `index`, `view`, `export`, `search`, `ask`, `impact`, `tests`, `mcp` |
| Tests and CI | About 880 tests; Linux and Windows, Python 3.11 and 3.12, on every push |
| Fixture score | 165 of 165 labelled edges, precision 1.0 |

What is honest to say about quality, and what is not yet known:

- **"Resolved" is not "correct."** The suite's resolved share (55% after Wave 3) counts raw calls that got any edge. Precision is measured only on the fixture (1.0) and the language samples. Precision on real repositories is the biggest unknown (question Q6).
- **The suite numbers predate T20 and T21.** Re-run it (`python -m eval.suite`, about 5 minutes) before quoting numbers.
- **T21 (#39) was merged without a review.** Reviewing it yourself is a good first exercise: `docs/tasks/T21-generic-adapter-scopes.md`, then the diff of #39.

## Decisions waiting for you

All in `docs/decisions.md`. Nothing is blocked on them; each was applied in a reversible
way so work could continue. Answer them as you reach the module in the reading order.

- **D-11 to D-23**: proposals, most already applied. Write yes, no or your change on the "Your call" line, then move the accepted ones into the Decided table.
- **Q1 to Q6**: the open questions. Q3 (should several weak paths add up?) and Q5 (when co-change lies) shape the impact engine v2.
- **Raised by the Wave 3 and 4 sessions** (each in its pull request's "Questions for the owner"):
  - T11: `/api/users/` and `/api/users` are treated as the same route (#28); the contract says a route key uses the path pattern as written.
  - T11f: axios base URLs travel in a new module attribute, `attrs["axios_instances"]` (#32); add it to the contract's list of common keys, or not.
  - T17a: Ruby stores the method name (`require`) in `RawImport.names` (#29), against the contract's "imported names".
  - T20: a receiver typed as an interface stays untyped; resolving it to the interface's method declaration needs a contract decision about method owners (#35).

## Open technical items

Small things the reviews found and left for later. None is urgent.

- **Impact engine v2** (yours to design): the co-change result says the graph alone misses what history knows. Combining the two, and answering Q3, is the core of v2.
- **JavaScript** is still the weakest deep language. Typed receivers (T20) help TypeScript; plain JavaScript needs JSDoc or a different approach for prototype methods and chains.
- **Precision on real code**: label a sample of edges on two real repositories by hand, the way the fixture was labelled.
- `pyproject.toml` says `mcp>=1.2`; the MCP server needs `mcp>=2`.
- The eval harness kills only the test process on a timeout, not its children.
- Search's embedding numbers were measured without `bge-small` (the download failed in the cloud); re-run `scripts/eval_search.py` locally.
- `--git` cannot find the checkout when the indexed source was a relative path and you run from another folder (intake stores the path as typed).
- C# `global using` applies only to its own file.

## CI/CD

CI runs `ruff` and `pytest` on Linux and Windows for every push and pull request
(`.github/workflows/ci.yml`). Next, in order:

1. **Branch protection on `main`** (GitHub Settings → Branches): require a pull request, require the four checks, require branches to be up to date. This stops a red pull request or a stale branch from reaching main.
2. **Coverage** in CI (`pytest --cov=codeatlas`).
3. **A nightly quality job**: the fixture score and the suite, with the results kept as artifacts; fail if fixture precision drops below 1.0.
4. **Dependabot** for Python packages and Actions versions.
5. **Deployment** to Render (below) once the demo exists.

## Deployment direction: a free public demo on Render

The goal is a public page anyone can open, that shows exactly how CodeAtlas works, and
that never calls a live LLM: no tokens burned, no keys on the server, nothing for a
visitor to abuse. The same approach as Antidote.

What already exists for this:

- **Record and replay.** The LLM layer saves every answer under a hash of the request, and `cache_mode = "replay_only"` answers only from saved answers. An unknown question raises an error instead of calling a provider (`llm/client.py`, `llm/config.py`).
- **The agent writes a trajectory** for every question: each step, each tool call, each result size. A recorded scenario can be shown step by step.
- **The viewer** is one self-contained HTML page, so it can be served as a static file.
- **Everything except `ask` is offline**: index, search, impact and tests need no LLM.

The likely shape (to decide when you get there):

1. Two or three **recorded scenarios** on repositories that index quickly. Examples: the fixture (a Python backend with a TypeScript frontend, where a backend change reaches frontend code through an HTTP route), plus one or two small real repositories. For each: a question for the agent, recorded once locally with real keys; an impact run on a real commit; a few searches.
2. The **index databases built at deploy time or committed** as small artifacts, so the server never clones anything on request.
3. A **small web app** (to choose: FastAPI with server-rendered pages, or a static site built from the recordings) that shows the map, lets a visitor run search and impact live on the pre-built indexes, and replays the agent's recorded answers step by step, clearly labelled as recorded.
4. Visitors **choose from the recorded questions**; they do not type their own, because a new question would need a live model.

Open questions for you:

- Does a visitor get to run anything live (search and impact are cheap and safe), or is everything a recording?
- Which repositories make the best story in under a minute?
- Static site (cheapest, no server) or a small server (live search and impact)?
- How the recordings stay in sync with the code: a script that re-records them when the agent or tools change.

## Suggested first week, hands-on

1. Set up locally (README, "Develop"), run the tests, index the fixture, open the viewer.
2. Turn on branch protection.
3. Read the contract and modules 1 to 3 from `docs/README.md`. Fill in your learning log as you go.
4. Review T21 (#39) yourself, using the reviewer agent first, then your own reading.
5. Answer Q1 and the decisions for the modules you have read.
6. Sketch the demo: pick the scenarios, then record the first one.
