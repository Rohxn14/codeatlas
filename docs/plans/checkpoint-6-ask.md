# Checkpoint 6: Ask in the app

Written Nov 17, 2026, for the owner to read before any code is written. Plan IDs refer
to `docs/plans/product-plan.md`.

## What the owner gets

A box on every repository page: "Ask a question about this repository". The answer
page shows each step the agent takes while it works (which tool, with what, how much
came back), then the answer. Every citation in the answer is a link that opens the file
at that line, and a citation that points nowhere is marked as invalid, not hidden.

## What exists already

- `agent/loop.py` `ask()`: the loop (model, tool calls, repeat, up to 20 steps), the
  citation check, and a trajectory file per question.
- `agent/tools.py`: 11 tools (search, symbol source, callers, impact, ...), each result
  capped at 4,000 characters.
- `llm/client.py`: Groq first, Gemini as fallback, retries, a cache that can replay
  recorded answers (`replay_only`).
- Tests already have a scripted fake model (`tests/agent/support.py`), so no test needs
  a key or the network.

Measured today: the first request for `itsdangerous` is about 7,600 characters (about
1,900 tokens): 2,200 for the system prompt, 5,400 for the 11 tool descriptions. Groq's
free tier allows about 8,000 tokens per minute, and every step resends the whole
conversation so far. That is why both earlier documented runs ran out (D1, D2).

## The steps, one pull request each

| Step | What | Needs keys? |
| --- | --- | --- |
| 6a | Groundwork in the agent: the trajectory keeps each tool's result, not only its size (D7: a replay cannot show what was never saved); a `search_docs` tool so the agent can read documentation sections (D-42 kept them out of code search); fix `python -m codeatlas.agent` looking for `codeatlas.sqlite` when `codeatlas index` writes `codeatlas.db` | no |
| 6b | The Ask page: a form, the question runs in the background like indexing (one at a time), the page reloads every 2 seconds and shows the steps so far, then the answer with linked citations. Tested with the scripted fake model | no |
| 6c | First real runs: five questions on PitwallOS and the fixture, with tokens, steps, seconds and valid citations per answer written down. Then the token cuts those numbers call for (D2), each measured before and after | **yes** |
| 6d | Follow-up questions in the same thread, if you want it (see question 3) | yes, for real runs |

## Rules this follows

- **Only the local app calls a model.** When the app is read-only (another host, or
  `--read-only`), the Ask box is not shown and the route refuses. A public demo will
  only replay recorded answers; that is later, with deployment.
- **Keys stay in your shell.** The page says which key is missing and how to set it
  (`$env:GROQ_API_KEY = "..."` in PowerShell, before `codeatlas serve`). It never shows,
  logs or stores a key.
- **No silent gaps.** A step-limit stop, a rate-limit failure, a cut tool result and an
  invalid citation are each said on the page.

## Questions for you (my recommendation first)

1. **Streaming.** The app has no JavaScript. The page can reload every 2 seconds and
   show whole steps (recommended: same as indexing, no new technology), or I can add a
   small script that streams words as they arrive (closer to a chat product, but the
   first JavaScript in the app).
2. **Who may ask.** Recommended: anyone using the local app, nobody on a read-only one.
   The alternative is a separate `--allow-ask` switch, off by default.
3. **Follow-ups (6d).** You said this should end up like a chatbot. A follow-up resends
   the earlier questions and answers, which costs tokens on a free tier. Recommended:
   build 6a to 6c first and decide 6d with the numbers from 6c.
4. **Where answers are kept.** Recommended: in memory while the app runs, plus the
   trajectory file on disk (already written today). The alternative is a table in the
   database, so past answers survive a restart; that is a schema change.

## What I will do before you answer

6a has no design choice in it beyond what is above, so I start there. 6b waits for your
answers to questions 1, 2 and 4, and 6c waits for your keys.

## Risks

| Risk | Sign | Response |
| --- | --- | --- |
| The free tiers cannot finish an answer | Rate-limit errors in 6c | Cut tokens (shorter tool descriptions, drop old tool results), measure, and report honestly what the free tiers can and cannot do |
| Answers cite lines that do not support the claim | Valid citations, wrong content | The check only proves a line exists. Read the five answers of 6c by hand and write down what was right |
| A long run blocks the app | Pages slow while an answer runs | The run is in a background thread, like indexing; measured in 6b |
