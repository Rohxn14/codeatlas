# T09: Agent loop, graph tools and MCP server

**Wave**: 2 (all of Wave 2 runs in parallel)
**Branch**: keep the one the cloud environment gives you

## Goal

An agent that answers questions about an indexed repository by calling tools over the graph, and cites `repo@sha:path:line` for every claim; and an MCP server that gives Claude Code (or any MCP client) the same tools. After this task the owner can ask "what calls `UserRepo.save`?" from the command line, or from Claude Code in VS Code.

## Files you may create or edit

- `src/codeatlas/agent/` (new package): the tools, the loop, the prompts, the MCP server, and `__main__.py`
- `tests/agent/`
- `docs/explainers/agent.md`

Do not edit `cli.py` (T18 edits it in parallel): the entry points are `python -m codeatlas.agent ask "..."` and `python -m codeatlas.agent mcp`; the `codeatlas ask` command is wired up later. Build stores for tests with `build_graph` from `src/codeatlas/indexer/pipeline/` (read `docs/explainers/pipeline.md`) or by writing nodes and edges directly.

## Part 1: the tools (`agent/tools.py`)

Each tool is a plain function over a `GraphStore` and a snapshot id, plus a `ToolSpec` (from `codeatlas.llm`) with a JSON schema. Every result is JSON-serialisable, says when it was cut short, stays under about 4,000 characters, and carries a `citation` for each symbol it names.

| Tool | Returns |
| --- | --- |
| `search_symbols(name, kind?, limit?)` | Symbols whose name matches, exact matches first |
| `semantic_search(query, k?)` | Hybrid search hits with spans. Use `codeatlas.search.HybridSearch` when that module is importable (T08 builds it in parallel); otherwise fall back to `store.search_text` and say so in the result |
| `get_symbol_source(key)` | Signature, docstring, span and the source lines, read from the indexed checkout (the snapshot's `source`; a URL source reads from `<data_dir>/repos/`) |
| `get_file_symbols(path)` | Everything defined in a file, in order |
| `find_callers(key, depth?, min_confidence?)` | Callers with their best path confidence (`store/graph.py`) |
| `find_callees(key, depth?, min_confidence?)` | The same, forwards |
| `get_imports(path)` | A module's IMPORTS edges, both directions |
| `compare_symbol_across_snapshots(key, snapshot_a, snapshot_b)` | Whether the symbol exists in each, and its signature and span in each |
| `traverse(key, edge_kinds, direction, depth ≤ 3)` | A bounded walk over chosen edge kinds |
| `impact(keys)` | v0: nodes that reach the given symbols over CALLS and IMPORTS, ranked by best path confidence, plus the changed files' co-change neighbours. T12 replaces this with the real impact engine; keep the signature |
| `select_tests(keys)` | v0: TEST nodes and test modules connected to the `impact` results through TESTS edges, ranked |

A twelfth tool in the project plan, `run_tests`, is **not** built: the agent never runs code from an indexed repository (CLAUDE.md, Safety). Say so in the explainer.

## Part 2: the loop (`agent/loop.py`)

`ask(question, store, snapshot_id, client: LLMClient, max_steps=20) -> Answer`:

1. A system prompt that describes the repository (languages and packages from the snapshot), the tools, and the rule: every claim about the code cites `repo@sha:path:line` from a tool result.
2. Call the model with the tools; run each tool call; append the results; repeat until the model answers without tool calls or `max_steps` is reached (then answer with what is known and say the limit was hit).
3. **Check citations**: parse every citation in the answer; a citation is valid when its path is a file of the snapshot and its line is within that file's module span. Return the answer with the list of invalid citations; never silently drop them.
4. Write a trajectory to `<data_dir>/trajectories/<UTC time>.jsonl`: one line per step (messages, tool calls, tool result sizes, tokens, seconds), so the evaluation and, later, strategy memory can read it.

`python -m codeatlas.agent ask "question" [--db PATH] [--snapshot ID]` prints the answer, the citations with a mark for invalid ones, and the steps taken.

## Part 3: the MCP server (`agent/mcp_server.py`)

`python -m codeatlas.agent mcp [--db PATH] [--snapshot ID]` serves the same tools over stdio with the `mcp` package (already a dependency). Tool names, descriptions and schemas are the ones from Part 1, so the agent and Claude Code see the same interface. In the explainer, give the exact command for adding it to Claude Code (`claude mcp add codeatlas -- python -m codeatlas.agent mcp --db <path>`) and how to check it is listed.

## Tests

- Every tool on a small multi-file repository indexed in the test, with exact expected results, including truncation and citations.
- The loop with a scripted fake provider: a two-step tool call then an answer; the step limit; an answer with one invalid citation, which is reported; the trajectory file has one line per step.
- `semantic_search` falls back to text search when `codeatlas.search` is missing (simulate the import failing).
- The MCP server lists all eleven tools with their schemas (use the `mcp` package's in-memory client or call the server's list handler directly); no network.
- No test calls a real LLM.

## Measure and report

In the pull request: five questions about the fixture, asked with the real LLM in the cloud session (the environment attaches the keys), with each answer, its citations and whether they are valid, steps and tokens. Use questions a developer would ask ("what breaks if `Repo.save` changes?", "which frontend code calls `GET /api/users/{id}`?"). Expect weak answers where the resolvers are not merged yet; say which answers would change once T06 and T07 merge. Also report that the MCP server starts and lists its tools.

## Done when

Tests pass on Linux and Windows CI; the five questions are reported; the explainer covers each tool, the loop step by step with one real trajectory, the citation check, and how to connect the MCP server to Claude Code.
