# T04: LLM layer and embeddings

**Wave**: 1 (parallel with T01 to T03, T05)
**Branch**: `task/T04-llm-layer`

## Goal

One provider-agnostic client for chat and tool calling, with Groq first and Gemini as fallback, a record-and-replay cache so evaluations never pay twice for the same call, and a local embeddings client.

## Files you may create or edit

- `src/codeatlas/llm/` (any modules inside it)
- `tests/llm/`, `tests/data/llm/` (recorded fixtures)
- `docs/explainers/llm-layer.md`

## API

| Piece | Shape |
| --- | --- |
| `Message` | role (`system`, `user`, `assistant`, `tool`), content, optional `tool_call_id`, optional `tool_calls` |
| `ToolSpec` | name, description, JSON-schema parameters |
| `ToolCall` | id, name, arguments (dict) |
| `LLMResponse` | text, tool_calls, provider, model, input_tokens, output_tokens, cached (bool) |
| `LLMClient.chat(messages, tools=None, temperature=0.0, max_tokens=None) -> LLMResponse` | The only call the rest of the project uses |
| `EmbeddingClient.embed(texts: list[str]) -> numpy.ndarray` | Float32, L2-normalised rows |

## Behaviour

1. **Providers**: a Groq adapter (OpenAI-compatible chat API with tools) and a Gemini adapter (`google-genai` SDK with function declarations). Each converts `Message`/`ToolSpec` to and from the provider format. Model names come from config; for both providers, if the configured model is gone, list the provider's models at startup and fall back to the newest one of the same family, logging the switch.
   - **Groq**: default model gpt-oss-20b (Groq id `openai/gpt-oss-20b`; confirm against the model list). The owner's smoke test reached it with status 200 through the environment's network secret.
   - **Gemini**: Google's documentation now calls `generateContent` the legacy API and recommends its newer Interactions API for new projects; current examples use `gemini-3.8-flash`. Use the SDK's generate-content call, which is still documented, behind the adapter, so a later move to the Interactions API touches one file. Default model `gemini-3.8-flash`, configurable. In the owner's smoke test, Gemini calls failed for a reason not yet known. Your live Gemini test is where it gets diagnosed: report the exact status code and error message, and whether listing models (`GET /v1beta/models`) works. A failing live Gemini test does not block this task.
2. **Fallback**: try providers in priority order. On rate limits (429), server errors (5xx) or timeouts, retry with exponential backoff and jitter (max 3 tries per provider), then move to the next provider. Never fall back on a 400-class request error; raise it.
3. **Record and replay cache**: key = SHA-256 of a canonical JSON of (provider-independent request: messages, tools, temperature, max_tokens, and a `cache_namespace` string). Stored in SQLite at `.codeatlas/llm_cache.sqlite`. Modes from config or `CODEATLAS_LLM_CACHE`: `off`, `read_write` (default), `replay_only` (raise on a miss: used by tests and reproducible evals).
4. **Config**: `codeatlas.toml` section `[llm]` with provider order, models, timeouts and cache mode; environment variables override. Keys come from `GROQ_API_KEY` and `GEMINI_API_KEY` when present; in the cloud environment the proxy may attach them instead, so a missing key is not an error until a request actually fails authentication.
5. **Embeddings**: `fastembed` with `BAAI/bge-small-en-v1.5` by default (configurable), batching, and a cache keyed by (model, text hash) in the same SQLite file.
6. **Usage log**: append one JSON line per real (non-cached) call to `.codeatlas/llm_usage.jsonl` with provider, model, tokens and latency, so the owner can see what the free tiers consumed.

## Tests

All offline: mocked HTTP responses for both providers, including tool calls, a 429 then success, a 5xx on Groq falling back to Gemini, and a 400 that is raised; cache hit and miss in each mode; canonical key stability (dict key order does not change the key); embeddings mocked so tests do not download models. One `@pytest.mark.live` test per provider, skipped by default, for a real round trip.

## Done when

All offline tests pass; the live test passes in the cloud environment when run with `pytest -m live` (report the result in the pull request); explainer written, including a sequence of what happens on a 429.

## Review of PR #7 (Oct 30)

**Verdict**: merge after fixes. **Fixes**: issue #14. Paste it into the T04 session (delete any of part 5's three small changes you disagree with first), wait for CI, then merge.

**What the PR does**: `codeatlas.llm`. `LLMClient.chat` tries Groq (`openai/gpt-oss-20b`) first and Gemini (`gemini-3.8-flash`) second, retries 429, 5xx and timeouts three times per provider with backoff, and raises 400-class errors at once. Answers go into a SQLite cache keyed by a provider-independent SHA-256 (modes off, read_write, replay_only); each real call adds a line to a JSONL usage log; embeddings use fastembed, cached by model and text hash.

**Live tests in the cloud**: Groq passed. Gemini failed on Google's side: listing models returned 200, but `generateContent` on 3.8-flash returned 503 "high demand", some tries got a 502 from the network proxy after about 30 s, and 2.5-flash returned 404 "no longer available to new users". Your working call from the laptop confirms the key is fine; the cloud failure was capacity or the proxy's cutoff.

| Check | Result | Evidence |
| --- | --- | --- |
| Scope | PASS | 31 files, all inside the brief; `pyproject.toml` untouched |
| Contract untouched | PASS | No diff in `models.py` or `indexer/adapter.py` |
| Tests | PASS | 182 passed, 2 live tests deselected; 38 for the LLM layer |
| Lint | PASS | `ruff check .` clean |
| Mutation spot-check | WARN | Treating 4xx as transient is caught; dropping tool schemas or `tool_call_id` from the cache key is not |
| Explainer | PASS | What, Why, How, Where, the 429 sequence, a model-family example |
| Brief coverage | WARN | Everything present; no test replays a tool call through the cache (the reviewer probed it: replay is exact) |
| Safety and secrets | PASS | Keys travel only in the `authorization` and `x-goog-api-key` headers, never in URLs, errors, the cache, the usage log or fixtures |
| Silent gaps | WARN | An empty answer (all thinking, MAX_TOKENS, SAFETY) is returned as `""` and cached for good (must fix 1) |

**Must fix** (issue #14, parts 1 to 3)
1. `gemini.py:137-161`, `groq.py:101-118`, `client.py:86-88`: empty answers are returned and cached. Raise `LLMEmptyResponseError` and fall back instead.
2. No way to turn thinking down. Your 163-of-175 thinking tokens count against the output limit, which is how empty answers happen. Add `gemini_thinking_level` (default low) and `groq_reasoning_effort` (default low).
3. `gemini.py:145`: made-up tool-call ids restart at `call_0` every turn, so a multi-turn agent history gets tool results under the wrong function name. This would break the agent loop (T09).

**Should fix** (issue #14, part 4): `replay_only` without a cache makes a real request; the cache-key test does not pin a key; the replay test checks only the text.

**Your decisions** (write your answer next to each)

| # | Question | Recommendation |
| --- | --- | --- |
| 1 | Cache key leaves out provider and model | Accept; keep the thinking level out too |
| 2 | Extra optional `ToolCall.signature` (in `llm/types.py`, not the contract) | Accept |
| 3 | Model check on first use, not at startup | Accept |
| 4 | Retired model falls back to the newest of its family, which may be `gpt-oss-120b` | Stay in the same size (D-17; issue part 5) |
| 5 | 401/403 raise instead of falling back | Accept; with one key set, use `CODEATLAS_LLM_PROVIDERS` |
| 6 | Embeddings ignore `replay_only` | Accept |
| 7 | SDKs instead of raw HTTP | Accept; neither SDK retries on its own |
| 8 | `[llm]` config read in `llm/config.py` | Accept for now |
| 9 | Gemini 404 for a retired model is raised as a request error | Re-run model resolution once (issue part 5) |
| 10 | 60 s timeout, longer than the proxy's ~30 s cutoff | Lower to 30 s (issue part 5) |
| 11 | Temperature 0.0, though Google advised 1.0 for Gemini 3 | Check the advice for 3.8 before the evaluation relies on it |

**Try it yourself** (PowerShell, after `gh pr checkout 7`, with `GROQ_API_KEY` and `GEMINI_API_KEY` set from your `.env`)

```powershell
foreach ($p in "groq","gemini") { $env:CODEATLAS_LLM_PROVIDERS=$p; $env:CODEATLAS_LLM_NAMESPACE="try-$p"; python -c "from codeatlas.llm import LLMClient, Message; c=LLMClient.from_config(); m=[Message('user','Reply with the single word: pong')]; a=c.chat(m); b=c.chat(m); print(a.provider, a.model, repr(a.text), a.cached, b.cached, a.output_tokens)" }
Get-Content .codeatlas\llm_usage.jsonl -Tail 2
Remove-Item Env:CODEATLAS_LLM_PROVIDERS, Env:CODEATLAS_LLM_NAMESPACE
```

Expect `groq openai/gpt-oss-20b 'pong' False True <n>`, then `gemini gemini-3.8-flash 'pong' False True ~170` (the count includes thinking tokens; a 503 means Google is busy). `False True` is the cache working: the second identical call never left your machine. The usage log shows one line per real call, none for cached ones.

**Read these yourself**
- `src/codeatlas/llm/client.py:67-116`: the whole cache, retry and fallback policy in 50 lines.
- `src/codeatlas/llm/providers/gemini.py:80-161`: the trickiest part (thought signatures, merged tool turns, made-up ids).
- `src/codeatlas/llm/cache.py:42-81`: what goes into the key decides what replays; check it matches your answer to question 1.
