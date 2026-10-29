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

1. **Providers**: a Groq adapter (OpenAI-compatible chat API with tools) and a Gemini adapter (`google-genai` SDK with function declarations). Each converts `Message`/`ToolSpec` to and from the provider format. Model names come from config, with the Groq model auto-resolved from the provider's model list when the configured one is retired.
2. **Fallback**: try providers in priority order. On rate limits (429), server errors (5xx) or timeouts, retry with exponential backoff and jitter (max 3 tries per provider), then move to the next provider. Never fall back on a 400-class request error; raise it.
3. **Record and replay cache**: key = SHA-256 of a canonical JSON of (provider-independent request: messages, tools, temperature, max_tokens, and a `cache_namespace` string). Stored in SQLite at `.codeatlas/llm_cache.sqlite`. Modes from config or `CODEATLAS_LLM_CACHE`: `off`, `read_write` (default), `replay_only` (raise on a miss: used by tests and reproducible evals).
4. **Config**: `codeatlas.toml` section `[llm]` with provider order, models, timeouts and cache mode; environment variables override. Keys come from `GROQ_API_KEY` and `GEMINI_API_KEY` when present; in the cloud environment the proxy may attach them instead, so a missing key is not an error until a request actually fails authentication.
5. **Embeddings**: `fastembed` with `BAAI/bge-small-en-v1.5` by default (configurable), batching, and a cache keyed by (model, text hash) in the same SQLite file.
6. **Usage log**: append one JSON line per real (non-cached) call to `.codeatlas/llm_usage.jsonl` with provider, model, tokens and latency, so the owner can see what the free tiers consumed.

## Tests

All offline: mocked HTTP responses for both providers, including tool calls, a 429 then success, a 5xx on Groq falling back to Gemini, and a 400 that is raised; cache hit and miss in each mode; canonical key stability (dict key order does not change the key); embeddings mocked so tests do not download models. One `@pytest.mark.live` test per provider, skipped by default, for a real round trip.

## Done when

All offline tests pass; the live test passes in the cloud environment when run with `pytest -m live` (report the result in the pull request); explainer written, including a sequence of what happens on a 429.
