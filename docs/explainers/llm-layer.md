# LLM layer

## What

`codeatlas.llm` is the only place CodeAtlas talks to a language model. Everything else calls one method:

```python
from codeatlas.llm import LLMClient, Message, ToolSpec

client = LLMClient.from_config()          # reads [llm] in codeatlas.toml, then env vars
reply = client.chat([Message("user", "Which file defines parse_args?")], tools=[...])
reply.text, reply.tool_calls, reply.provider, reply.cached
```

Behind that call it:

- tries **Groq** first (`openai/gpt-oss-20b`) and **Gemini** second (`gemini-3.8-flash`),
- retries rate limits, server errors and timeouts, then falls back to the next provider,
- **records** every answer in SQLite and **replays** it for an identical request, so an evaluation never pays twice,
- appends one line per real call to `.codeatlas/llm_usage.jsonl`, so you can see what the free tiers consumed.

`EmbeddingClient.embed(texts)` turns texts into unit-length float32 vectors locally with `fastembed` (`BAAI/bge-small-en-v1.5`), cached in the same SQLite file.

| File | Role |
| --- | --- |
| `types.py` | `Message`, `ToolSpec`, `ToolCall`, `LLMResponse`: the provider-independent shapes |
| `errors.py` | `LLMRequestError` (400-class, raise), `LLMTransientError` (429/5xx/timeout, retry), `LLMEmptyResponseError` (no text and no tool calls, fall back), `LLMUnavailableError`, `CacheMissError` |
| `config.py` | `LLMConfig` and `load_llm_config`: `[llm]` table, then environment overrides |
| `cache.py` | canonical cache key, `LLMCache` (chat answers and embedding vectors) |
| `providers/base.py` | the `Provider` protocol and the "model is gone" fallback rule |
| `providers/groq.py`, `providers/gemini.py` | one adapter per provider |
| `client.py` | `LLMClient`: cache, retry, fallback, usage log |
| `embeddings.py` | `EmbeddingClient` |

## Why

**One small interface, adapters behind it.** The agent, search and impact engine should not care who answered. Each adapter converts `Message`/`ToolSpec` to its wire format and back, and raises only our own error classes. Adding a provider, or moving Gemini to its newer Interactions API, touches one file.

**SDKs, with their own retries switched off.** The `groq` and `google-genai` packages are already dependencies and handle auth headers, URLs and response parsing. Both accept an `httpx.Client`, which is how the tests feed them mocked responses. Groq's SDK retries by default (`max_retries=2`). That would multiply our three tries into nine and hide the real count, so it is set to 0: the client owns the one retry policy.

**Classify errors by what to do next, not by provider.** A 429, 5xx or timeout says "try again later" (transient). A 400-class error says "this request is wrong", and Gemini would reject it too, so it is raised at once. That includes a 401: a bad key is a configuration problem, and falling back would hide it.

**An empty answer is a failure, not an answer.** Gemini's thinking tokens count against the output limit: a two-word prompt once spent 163 of 175 tokens thinking. When thinking uses the whole budget, or a safety filter blocks the answer, the response has no text and no tool calls. Returning `""` would look like success and, worse, be cached and replayed for good. So both adapters raise `LLMEmptyResponseError` with the finish or block reason, the client moves straight to the next provider (the same request would come back empty again), and nothing is cached.

**Thinking is turned down by default.** `gemini_thinking_level` (sent as `ThinkingConfig.thinking_level`) and `groq_reasoning_effort` (sent as `reasoning_effort`) both default to `low`; `"minimal"` suits cheap one-shot Gemini calls, and `""` leaves the provider's default. They stay out of the cache key, like the model.

**Cache key without the provider or model.** The brief asks for a provider-independent key: messages, tools, temperature, max tokens and a namespace. So an answer recorded from Groq replays even when Groq is down, which is what reproducible evaluations need. The cost: changing the model does not invalidate old answers. Use a new `cache_namespace` for that (see Questions in the PR). Gemini's thought signatures are also left out of the key, because they are opaque bytes that change on every live run and would make replays miss.

**Canonical JSON.** `json.dumps(sort_keys=True, separators=(",", ":"))` means `{"a":1,"b":2}` and `{"b":2,"a":1}` hash the same. Temperature is converted to `float`, so `0` and `0.0` agree too.

**Thought signatures (Gemini 3).** Gemini 3 returns an opaque `thought_signature` with each function call, and it rejects a later turn that sends the call back without one. `ToolCall` therefore has an optional `signature` (base64). For calls that Groq made, which have no signature, the adapter sends the placeholder value Google documents for this case (`skip_thought_signature_validator`). Without this, falling back to Gemini in the middle of an agent loop would fail with a 400.

**Lazy model check.** "If the configured model is gone, pick the newest of its family" needs a network call. A size such as `20b` is part of the family (decision D-17), so `gpt-oss-20b` never silently becomes `gpt-oss-120b`, which has different limits and cost. A model retired *after* the first check shows up as a 404; the client then looks the model up once more and retries if a different one is found. Doing it in the constructor would make `LLMClient.from_config()` slow and network-bound even when everything is cached. So it runs once per provider, just before that provider's first real call. If the listing fails, the configured model is kept, and the chat call then reports the real error.

**Where keys come from.** Providers read `GROQ_API_KEY` and `GEMINI_API_KEY` from the environment, nothing else. On the owner's machine the `codeatlas` command fills them from a gitignored `.env` first (`envfile.py`, D-45); see `cli.md`.

**Missing keys are not an error.** In the cloud environment the proxy attaches keys, so the environment variables are often empty. Both SDKs refuse to start without a key, so a placeholder is passed. If nothing replaces it, the request fails with a 401, which surfaces as `LLMRequestError`.

Rejected: writing raw `httpx` calls for Groq (smaller, but duplicates what the SDK does), and LiteLLM-style routing libraries (a new dependency, and much more than we need).

## How

### A chat call

1. Build the cache key: SHA-256 of the canonical JSON of `{messages, tools, temperature, max_tokens, cache_namespace}`.
2. If caching is on, look the key up. On a hit, return it with `cached=True`. On a miss in `replay_only` mode, raise `CacheMissError`.
3. For each provider in order (default `groq`, then `gemini`):
   1. The first time, list its models. If the configured model is missing, switch to the newest one of the same family and log a warning.
   2. Skip it if it is **resting** after a rate limit (below).
   3. Skip it, and rest it until its minute resets, if the request will not fit: Groq's last answer said how many tokens are left this minute (`x-ratelimit-remaining-tokens`, reset in `x-ratelimit-reset-tokens`), and `estimate_tokens` (characters ÷ 4) says this request needs more. Sending it would only earn a 429.
   4. On a **429** (rate limited): do not retry. Rest this provider for as long as it asked (`retry-after` header, or "try again in 7.66s" / `retryDelay: "34s"` in the error), or 60 s if it did not say, and move to the next provider.
   5. On another `LLMTransientError` (5xx, timeout): try up to `max_tries` (3) times, sleeping `base·2^attempt + uniform(0, base)` (1–2 s, then 2–3 s) in between. `LLMRequestError` propagates immediately.
4. If the only providers left are resting, wait until the first is free and try it again, as long as the request's total wait stays within `max_wait_seconds` (60). `on_wait(seconds, label)`, when set, is called before each wait so a page can show it.
5. Otherwise raise `LLMUnavailableError` with each failure listed, including how long the next provider would have taken to be free.
6. Store the answer in the cache (unless the mode is `off`) and append the usage line: provider, model, tokens, latency, the estimate made before sending (`estimated_input_tokens`, to check the ÷ 4 rule against the real count), and Groq's `limits` (tokens left this minute, requests left today, when each resets). The usage log is where the real free-tier limits are measured.

### Sequence on a 429

```
caller            LLMClient                Groq               Gemini
  | chat(msgs) ---> |                         |                   |
  |                 | cache lookup: miss      |                   |
  |                 | GET /models (first use) |                   |
  |                 | POST chat --------------> 429, "try again in 7.66s"
  |                 | Groq rests until now + 7.66 s               |
  |                 | GET /models (first use) ------------------->|
  |                 | POST generateContent ---------------------->| 200
  |                 | cache put, usage line   |                   |
  | <-- LLMResponse(provider="gemini", cached=False)              |
  | chat(next) ---> | Groq is resting: skipped, no request        |
  |                 | POST generateContent ---------------------->| 200
```

Why not retry a 429 the way a 5xx is retried: free tiers limit tokens per minute, so a 429 does not lift in one or two seconds. Before this change (Nov 18) one agent question sent Groq 13 requests that were all refused: three quick tries per step, and every new step started with Groq again. The 429 was measured, not guessed: each step's input grew from 1,841 to 7,660 tokens, and three steps in three seconds used about 7,200 of the minute's budget.

The default chain is Groq `gpt-oss-20b`, then Groq `gpt-oss-120b`, then Gemini (`groq_fallback_models`, the owner's order on Nov 18). Groq counts its limits per model, so when 20b's minute is used up, 120b usually still has its own.

Providers are kept apart by their position in the list, not their name, so two models of one provider (Groq 20b and 120b) rest separately: each has its own limits.

### Worked example: model family

Groq lists `openai/gpt-oss-20b` (created 1754407957), `openai/gpt-oss-120b` (1754408224) and `openai/gpt-oss-safeguard-20b`. Suppose the config says `openai/gpt-oss-10b`, which is not listed.

- `model_family("openai/gpt-oss-10b")` blanks version numbers but keeps sizes: `openai/gpt-oss-10b`.
- No listed model has that family: `gpt-oss-20b` and `gpt-oss-120b` are other sizes, and `safeguard` is another name. So the configured model is kept, a warning lists what is available, and the chat call reports the real error.
- With versions it works as before: `llama-3.1-8b-instant` missing among `llama-3.3-8b-instant` and `llama-3.3-70b-instant` picks `llama-3.3-8b-instant`.

Gemini lists no dates, so `gemini-3.8-flash` missing among `gemini-3.7-flash` and `gemini-3.9-flash` picks `3.9`. `gemini-3.9-flash-lite` is a different family because of `-lite`.

### Embeddings

1. Hash each text with SHA-256.
2. Fetch the cached vectors for `(model, hash)`.
3. Embed only the missing texts, in batches of `embedding_batch_size`, with duplicates embedded once.
4. L2-normalise each vector, store it as float32 bytes, and return the rows in input order.

The fastembed model loads on first use, so a fully cached call never downloads weights.

### Configuration

```toml
[llm]
providers = ["groq", "gemini"]
groq_model = "openai/gpt-oss-20b"
groq_fallback_models = ["openai/gpt-oss-120b"]  # tried next, each with its own limits
gemini_model = "gemini-3.8-flash"
gemini_thinking_level = "low"  # "" | minimal | low | medium | high
groq_reasoning_effort = "low"  # "" | low | medium | high
timeout_seconds = 30
max_tries = 3
max_wait_seconds = 60         # longest wait per request when every provider is rate limited
cache = "read_write"          # off | read_write | replay_only
cache_namespace = "default"
embedding_model = "BAAI/bge-small-en-v1.5"
embedding_batch_size = 64
```

Environment variables override these: `CODEATLAS_LLM_PROVIDERS` (comma-separated), `CODEATLAS_GROQ_MODEL`, `CODEATLAS_GROQ_FALLBACK_MODELS` (comma-separated), `CODEATLAS_GEMINI_MODEL`, `CODEATLAS_GEMINI_THINKING`, `CODEATLAS_GROQ_REASONING`, `CODEATLAS_LLM_TIMEOUT`, `CODEATLAS_LLM_MAX_WAIT`, `CODEATLAS_LLM_CACHE`, `CODEATLAS_LLM_NAMESPACE`, `CODEATLAS_EMBEDDING_MODEL`. Keys come from `GROQ_API_KEY` and `GEMINI_API_KEY` when set. Files go under `[paths] data_dir`: `llm_cache.sqlite` and `llm_usage.jsonl`.

## Where

- **Used by**: hybrid search (`EmbeddingClient`), the agent loop (`LLMClient.chat` with tools), and the eval harness. The harness runs with `CODEATLAS_LLM_CACHE=replay_only` for reproducible runs and a fresh `CODEATLAS_LLM_NAMESPACE` per experiment.
- **Contract types**: none. The LLM layer does not touch `models.py` or `adapter.py`. Its own types live in `llm/types.py`. It reuses `codeatlas.config` only for `CONFIG_FILENAME` and `[paths] data_dir`.
- **Tests**: `tests/llm/` mock HTTP with `httpx.MockTransport` and recorded JSON in `tests/data/llm/`. `tests/llm/test_live.py` makes one real round trip per provider and runs only with `pytest -m live`.
