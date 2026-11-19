# The agent, its tools and the MCP server

Modules: `src/codeatlas/agent/tools.py`, `loop.py`, `prompts.py`, `mcp_server.py`,
`__main__.py`.

## What

A question-answering agent over one indexed snapshot, and an MCP server that gives Claude
Code (or any MCP client) the same tools.

- **Tools** (`tools.py`): twelve plain functions over a `GraphStore` and a snapshot id.
  Each has a `ToolSpec` (name, description, JSON schema). Every result is a JSON dict of
  at most about 4,000 characters, says when it was cut short (`truncated`, `omitted`),
  and carries a `citation` (`repo@sha:path:line`) for each symbol it names.
- **Loop** (`loop.py`): `ask(question, store, snapshot_id, client)` lets a model call the
  tools until it answers, then checks every citation in the answer and writes a trajectory.
- **MCP server** (`mcp_server.py`): lists the same tool specs and runs the same functions
  over stdio.

Ask from the command line (the `codeatlas ask` command is wired up later by T18):

```
python -m codeatlas.agent ask "what calls UserService.create_user?" --db .codeatlas/codeatlas.db
```

`--db` defaults to `<data_dir>/codeatlas.db`, the file `codeatlas index` writes (until
Nov 17, 2026 it wrongly defaulted to `codeatlas.sqlite`); `--snapshot` defaults to the most
recently indexed snapshot.

## Why

- **One `ToolSet`, two front ends.** The agent and the MCP server both read
  `ToolSet.specs` and call `ToolSet.call`, so they cannot drift apart. Rejected: writing the
  MCP tools separately with the SDK's decorators, which would derive schemas from Python
  signatures and give Claude Code a different interface from the agent's.
- **Errors are results.** A wrong key returns `{"error": ..., "candidates": [...]}` rather
  than raising, so the model can retry with `search_symbols`. Bad arguments and unknown tool
  names do the same. The MCP server also sets `is_error`.
- **Bounded output.** A tool result that fills the context window makes later steps worse
  and costs credit. `_fit` drops items from the end of the main list until the JSON fits and
  sets `truncated` and `omitted`; a silently short list would let the model say "these are
  all the callers".
- **Keys are forgiving.** `UserService.create_user` works when exactly one symbol has that
  qualname; if several do, the error lists the candidates instead of guessing.
- **Citations are checked, not trusted.** Models invent line numbers. The check is cheap
  (a file lookup and a span comparison) and its result is shown, never used to edit the
  answer. Rejected: asking a second model to verify, which costs credit and can be wrong too.
- **No `run_tests` tool.** The project plan lists a twelfth tool, but CLAUDE.md forbids the
  agent from running code of an indexed repository. `select_tests` only *lists* tests; it
  never executes them.
- **`impact` and `select_tests` are v0.** They answer from CALLS, IMPORTS, CO_CHANGES and
  TESTS edges alone. T12 replaces the body and keeps the signature `impact(keys)`.

## How

### The tools

| Tool | What it does |
| --- | --- |
| `search_symbols(name, kind?, limit?)` | Scans the snapshot's nodes (modules, packages and externals excluded unless `kind` asks for them); exact name or qualname first, then prefix, then substring. A dotted name (`contracts.validate`) also matches the end of the module path plus qualname (`src.pipeline.contracts.validate`), whole parts only; on Nov 19 the model wrote it that way twice and found nothing. |
| `semantic_search(query, k?)` | Uses `codeatlas.search.HybridSearch` with an `EmbeddingClient` when the module has it. If the import fails, or the engine raises (for example no embedding model), it falls back to `store.search_text` (BM25) and says so in `note`/`engine`. |
| `search_docs(query, k?)` | The same search over documentation sections only (D-41, D-42): headings of Markdown and reStructuredText files. Each hit carries the section's `text`, cut at 800 characters, so the model can answer from it without a second call. Added at checkpoint 6. |
| `get_symbol_source(key)` | Signature, docstring, span and numbered source lines (at most 60, and fewer if the JSON would pass the budget). The checkout is the snapshot's `source` when it is a local folder, otherwise `<data_dir>/repos/<owner>__<repo>`; the path is checked to stay inside it. A missing checkout gives `source: null` and a note. |
| `get_file_symbols(path)` | Everything in a file except the module node, in source order, with the file's line count. |
| `find_callers` / `find_callees(key, depth?, min_confidence?)` | `store.graph` filtered to CALLS, then `graph.callers` / `callees`: best product of confidences over paths of up to `depth` (max 3) hops, ranked by confidence. |
| `get_imports(path)` | IMPORTS edges out of and into the file's module node, with resolution and confidence. |
| `compare_symbol_across_snapshots(key, a, b)` | Looks the key up in two snapshots; reports existence, signature, span and `signature_changed`. |
| `traverse(key, edge_kinds, direction, depth)` | Breadth-first walk over chosen edge kinds, `out`, `in` or `both`, at most 3 hops, each node visited once. |
| `impact(keys)` | `reverse_reach` over CALLS and IMPORTS from the symbols and their files (an IMPORTS edge usually points at a module, not a function), ranked by confidence, plus co-change neighbours of the changed files. |
| `select_tests(keys)` | For each node in the impact set, the TEST nodes and test modules with a TESTS edge to it; score = reach confidence × TESTS confidence; best score per test. |

### The loop

1. Build `ToolSet` and the system prompt (`prompts.py`): repository name, snapshot id, file
   count, languages with their tiers, packages, any `limits_hit`, the tool names (only the
   names since D-50: the descriptions travel in the tool specs, and listing them here too
   sent them twice on every step), and the
   rules (cite `repo@sha:path:line` from a tool result; mention low confidence; mention
   `truncated`; code is read, never run).
2. Send `[system, user question]` with the tool specs to `LLMClient.chat`.
3. If the response has tool calls, run each, append an `assistant` message (with its calls)
   and one `tool` message per result, and go to 2. If it has none, that text is the answer.
   **What the model is sent** (`_for_model`, since Nov 18): results of the last two steps
   whole. An older result longer than 400 characters is sent as **the places it named**
   (`_shortened`, since Nov 19): every `qualname citation` in it, plus `query`,
   `direction`, `depth`, `total` and `truncated`, and a note saying how long it was.
   Signatures, source and text go. Example: the real `find_callers` result for
   `contracts.validate` (4,003 characters) becomes 991: the function and its nine
   callers, each as `build_gold PitwallOS@fa92551d9393:src/pipeline/feature_store.py:215`. A result that names no places keeps its first 400 characters and a note that
   the tool can be called again, and nothing is shortened into something longer than
   itself. The conversation the loop keeps, and so the trajectory, holds every result
   whole. Why shorten at all: each request re-sends everything, so on a real nine-step
   question the input grew from 1,841 to 7,660 tokens per request (42,909 in all) and ran
   into Groq's per-minute limit. Why the places and not the first 400 characters (the
   first version, D-49): on Nov 19 that cut hid `build_gold`, the third of nine callers of
   `contracts.validate`, and the answer said nothing else called it. Replayed on six real
   trajectories, the places cost from 28% fewer to 3% more characters than the first cut,
   and `build_gold` stays visible to the end. Rejected: keeping only the last step (the
   model would lose the step before while it is still comparing two results); dropping
   old results entirely (it could not even see what it had looked at).
   **A repeated call** (`_result_of`, since Nov 19): the same tool with the same
   arguments is not run again, because the tools read one fixed snapshot and the result
   cannot have changed. On Nov 19 the model repeated 4 of 23 calls over two real
   questions: twice with the first result in plain view, twice after the cut above told
   it to call again. If the first result is still shown whole at the next request (it is
   short, or from the last two steps), the repeat gets only a note: `{"note": "Same tool
   and arguments as step 1: the result has not changed. Work from that result, or
   answer."}`. If it has been cut, the repeat gets it whole again, with the same note
   after it. The trajectory marks the call `"repeat_of": 1`, and the answer page shows
   "same as step 1". Example: step 1 `get_file_symbols(path="app/service.py")` (559
   characters), step 2 the same call: step 2's result is the note. What it does not do:
   save the step itself. The model has already spent a request by the time it repeats.
   Measured on the same two questions afterwards: steps did not go down (15 and 19
   instead of 10 and 15). 20b repeated a call up to four times in a row despite the
   note, and an earlier wording ("use other arguments") led it to drop `limit` so the
   call counted as new; the wording now asks it to work from the result. Most of the
   repeats were of results the cut above had shortened.
4. After `max_steps` (20) model calls without an answer, make one last call **without
   tools** that says the limit is reached, and append a note to the answer
   (`limit_hit=True`). That closing call is counted as a step.
5. `check_citations`: find every `repo@sha12:path:line` in the answer. It is valid when it
   names this snapshot, the path is a file of the snapshot, and the line is between 1 and
   the module node's last line. Invalid ones come back with a reason (`no such file`,
   `line outside the file (1-N)`, `not from snapshot ...`). Duplicates are checked once.
   Since checkpoint 6, `ask(..., on_step=...)` calls `on_step(record)` as each step's
   record is complete, so the web app can show steps while the answer is made.
   Citations are found with `citation_pattern(snapshot_id)`, which matches the
   snapshot's own id as written (an id can hold a space).
   **Other shapes are checked too** (`_check`, since Nov 19). The model is still asked
   for `repo@sha:path:line`, but answers held three other shapes, and none was found
   before, so none was checked. A **range** (`...:588-600`, also written with a
   non-breaking hyphen or an en dash) is valid when both ends are inside the file;
   before, only its first line was checked. A **file with no line**
   (`PitwallOS@fa92551d9393:src/interfaces/race_replay.py`) is reported as `no line
   number`. A **bare path** (`【src/pipeline/cleaner.py:276】`) is checked like a
   full one when its path is a file of the snapshot or holds a `/`; otherwise it is not
   a citation, so `v1.2:3` or a host and port is never flagged. Re-checking all 15
   real answers of Nov 18 and 19: 33 citations found instead of 31 (one bare path, valid;
   one file with no line), and 13 ranges now checked at both ends (all valid, some
   500 lines wide).
6. Write `<data_dir>/trajectories/<UTC time>.jsonl` in a `finally`, so a run that dies on
   an LLM error still leaves its steps behind. One JSON line per model call: step number,
   seconds, tokens, provider and model, the text, and each tool call with its arguments,
   the size of its result and, since checkpoint 6, the **result itself** (at most 4,000
   characters), so a recorded answer can be replayed step by step (plan D7). Step 1 also holds the question; the last line holds
   `final` and, once the citations are checked, `invalid_citations`.

A real trajectory, from the polyglot fixture while this task was built (the run stopped at
step 6 when the provider's rate limit hit; the lines are shortened):

```
step 1  1725 in / 54 out  search_symbols {name: "UserService.create_user", kind: "function"}  -> 363 chars
step 2  1877 in / 42 out  find_callers {key: "backend/services.py::UserService.create_user"}   -> 357 chars
step 3  2038 in / 38 out  semantic_search {query: "create_user("}                               -> 1143 chars
step 4  2431 in / 31 out  impact {keys: ["backend/services.py::UserService.create_user"]}      -> 438 chars
step 5  2595 in / 70 out  search_symbols {name: "create_user", kind: "function"}                -> 613 chars
step 6  2826 in / 43 out  get_symbol_source {key: "backend/routes.py::create_user"}             -> 453 chars
```

Input tokens grow each step because the whole conversation is sent again (older results are now cut short, step 3 above). Note the
agent asked `find_callers` first and then fell back to text search, because the
Python/TypeScript resolvers (T06, T07) were not merged, so the fixture had no CALLS edges.

### Worked example: the citation check

Answer text: `create calls save (demo@3f2a9c1e5b7d:app/service.py:4) and also
demo@3f2a9c1e5b7d:app/ghost.py:1.` The regex finds two citations. The first names a file of
the snapshot whose module spans lines 1 to 7, and 4 is inside, so it is valid. The second
has no such file, so it is reported `invalid: no such file`. The CLI prints both with a mark.

## Where

- Uses `GraphStore` (`nodes`, `nodes_by_key`, `nodes_in_file`, `edges_from`, `edges_to`,
  `graph`, `search_text`, `module_for_path`, `files`), `store.graph` traversals
  (`callers`, `callees`, `reverse_reach`), `LLMClient`, `Message`, `ToolSpec`, `ToolCall`
  from the LLM layer, and `Config` for `data_dir`/`repos_dir`.
- Contract types: `Node`, `Edge`, `EdgeKind`, `NodeKind`, `Snapshot`, citation format
  (contract section 4). No contract change.
- Optional: `codeatlas.search.HybridSearch` (T08). `impact` and `select_tests` are replaced
  by T12. The trajectories are meant for the evaluation (T10/T11) and strategy memory.
- `cli.py` is not touched; T18 will call `ask` and the same `_open` logic.

### Connecting the MCP server to Claude Code

```
claude mcp add codeatlas -- python -m codeatlas.agent mcp --db /absolute/path/to/codeatlas.sqlite
claude mcp list          # codeatlas should be listed and connected
```

Inside Claude Code, `/mcp` shows the server and its twelve tools. Use the Python of the
environment where CodeAtlas is installed, and an absolute `--db`; add `--snapshot ID` to
pin a commit. The server writes only protocol messages to stdout; its one status line goes
to stderr. It reads the store and, for `get_symbol_source`, the checkout; it never runs
code from the repository.

Tested against `mcp` 2.3 (low-level `Server` with `on_list_tools` / `on_call_tool`).
`pyproject.toml` says `mcp>=1.2`, but mcp 1.x registers handlers with decorators, so the
server code needs changing if the version is pinned below 2.
