# Day 1: Thursday, Oct 29

**By tonight**: the contract is typed and pushed, the cloud environment works, T00 is reviewed and merged, and the six Wave 1 sessions run overnight.

**Your four hours**:

| # | Step | Who | Time |
| --- | --- | --- | --- |
| 1 | Install Claude Code and check your tools | You | 15 min |
| 2 | Turn the folder into a repository and push it to GitHub | You | 10 min |
| 3 | Type the contract | You | 90 min |
| 4 | Set up the cloud environment; decide on Fable | You | 20 min |
| 5 | Smoke-test the environment | Cloud session | 5 min of yours |
| 6 | Launch T00, then answer Q1 to Q4 in the decision log while it runs | Cloud session and you | 45 min of yours |
| 7 | Review and merge T00 | Reviewer subagent, then you | 45 min |
| 8 | Launch Wave 1 before you sleep | Cloud sessions | 10 min |

Agent time is not counted: T00 and Wave 1 run while you do other things or sleep.

## 1. Install Claude Code and check your tools

Open PowerShell (not CMD) and install the Claude Code CLI. The VS Code extension has its own copy for its panel, but `claude --cloud` and `claude --teleport` need the standalone CLI in your terminal:

```powershell
irm https://claude.ai/install.ps1 | iex
```

Close PowerShell, open a new window, then check everything:

```powershell
claude --version        # prints a version number; if "not recognized", see the troubleshooting page
claude                  # first run: log in with your claude.ai account in the browser, then type /exit
git --version
gh auth status          # if not logged in: gh auth login
python --version        # 3.11 or newer
node --version          # 20 or newer; needed later for the TypeScript fixture, fine to install tomorrow
```

In VS Code, install the Claude Code extension (Extensions → search "Claude Code" → Install) if it is not there yet.

## 2. Turn the folder into a repository and push it to GitHub

The kit is already in `C:\Users\Rohan\Desktop\Projects\CodeAtlas`. Open that folder in VS Code (File → Open Folder), open the integrated terminal (Ctrl+`), and run:

```powershell
# two kit files had to arrive in _move-me; put them where they belong
New-Item -ItemType Directory -Force .claude\agents, .github | Out-Null
Move-Item _move-me\reviewer.md .claude\agents\reviewer.md
Move-Item _move-me\pull_request_template.md .github\pull_request_template.md
Remove-Item _move-me

git init -b main
python -m venv .venv
.\.venv\Scripts\Activate.ps1
git add .
git status              # .venv must NOT appear; the .gitignore keeps it out
git commit -m "docs: project kit"
gh repo create codeatlas --private --source . --remote origin --push
```

If PowerShell refuses to run `Activate.ps1`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try again.

Then install the Claude GitHub App on the repository: open github.com/apps/claude, choose Configure, and select `codeatlas`. Without it, `claude --cloud` uploads a bundle of your local folder instead of cloning from GitHub.

## 3. Type the contract

1. Read `docs/contract.md` once, end to end, before typing anything. Since yesterday it gained the repository layer: `PACKAGE` nodes, `DEPENDS_ON` and `CO_CHANGES` edges, the `STRUCTURAL` tier, the `IMPORT_SCOPED`, `CONVENTION` and `HISTORY` resolution levels, and a `RepoAnalyzer` interface.
2. Create `src/codeatlas/__init__.py` and `src/codeatlas/indexer/__init__.py`, both empty.
3. Type `src/codeatlas/models.py` (sections 3 to 6) and `src/codeatlas/indexer/adapter.py` (section 7).
4. Type, do not paste. When you cannot say why a field exists, write the question under "Open" in `docs/decisions.md` instead of guessing.
5. Check that both files import:

   ```powershell
   python -c "import sys; sys.path.insert(0, 'src'); import codeatlas.models, codeatlas.indexer.adapter; print('ok')"
   ```

6. Commit and push:

   ```powershell
   git add src
   git commit -m "contract: models and adapter interfaces"
   git push
   ```

## 4. Set up the cloud environment

At claude.ai/code, open the environment selector under the message box → New environment.

**Name**: `codeatlas`

**Network access**: Custom. Tick "Also include default list of common package managers", then add:

```
huggingface.co
*.huggingface.co
*.hf.co
```

**Network secrets** (Add secret, one at a time):

| Name | Allowed websites | Header name | Prefix | Value |
| --- | --- | --- | --- | --- |
| Groq | `api.groq.com` | `Authorization` | `Bearer` | your Groq key |
| Gemini | `generativelanguage.googleapis.com` | `x-goog-api-key` | (leave empty) | your Gemini key |

**Environment variables**:

```
BASH_DEFAULT_TIMEOUT_MS=600000
CODEATLAS_LLM_CACHE=read_write
```

**Setup script**:

```bash
#!/bin/bash
npm install -g @sourcegraph/scip-python @sourcegraph/scip-typescript || true
pip install fastembed || pip install --break-system-packages fastembed || true
python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')" || true
exit 0
```

Then, in a local `claude` session in the repo folder, run `/remote-env` and pick `codeatlas`.

**Decide on Fable.** The bonus credit can pay for Fable in cloud sessions, but on the Pro plan Fable also needs usage credits turned on with a balance, and bills them once the bonus is spent. If you want Fable for the five core tasks (T06, T07, T12, T15, T16), turn on usage credits in your claude.ai settings under Usage, with a low monthly cap and a small balance. T00 runs on the default model either way, so you can decide after seeing its cost.

## 5. Smoke-test the environment

Start one short session on the repo in the `codeatlas` environment (claude.ai/code, or `claude --cloud` with the prompt below):

> Do not change any files. Report the result of each step:
> 1. `scip-python --version` and `scip-typescript --version`.
> 2. One minimal chat request to Groq and one to Gemini using curl, without setting any API key yourself. Report each HTTP status code.
> 3. `git clone --filter=blob:none https://github.com/pallets/click /tmp/click-test`, then `git -C /tmp/click-test log --oneline --no-renames --name-only -5`: did both work?
> 4. `python -c "import sqlite3; c = sqlite3.connect(':memory:'); c.execute('create virtual table t using fts5(x)'); print('fts5 ok')"`

What the results mean:

| Result | Meaning | Action |
| --- | --- | --- |
| Both LLM calls return 200 | The proxy attaches your keys | Nothing |
| A 401 | The key is not reaching the API | Tell me the error; we move that key to an environment variable on this personal environment |
| Clone or log fails | Sessions cannot fetch repos they were not started on | Tell me; the acceptance suite then runs on your laptop overnight instead |
| FTS5 fails | SQLite lacks full-text search | Tell me before Wave 1; T03 depends on it |

## 6. Launch T00 (default model)

```powershell
git pull
claude --cloud "Execute docs/tasks/T00-scaffold.md. Follow CLAUDE.md."
```

While it runs, answer Q1 to Q4 in `docs/decisions.md` and send me your answers; I will push back on each. Q5 and Q6 can wait until tomorrow.

## 7. Review and merge T00

1. In VS Code, open a local `claude` session in the repo and ask: "Use the reviewer agent on task/T00-scaffold." Read its report.
2. Then follow section 3 of `docs/history/cloud-playbook.md` at deep depth. T00 sets the patterns every later session copies (layout, test style, explainer depth), so this review matters more than most.
3. Note T00's cost in the usage menu: it is the baseline for budgeting every later wave.
4. Squash merge, then fill in the T00 entry of `docs/learning-log.md`.

## 8. Launch Wave 1 before you sleep

```powershell
git switch main
git pull
claude --cloud "Execute docs/tasks/T01-python-adapter.md. Follow CLAUDE.md."
claude --cloud "Execute docs/tasks/T02-typescript-adapter.md. Follow CLAUDE.md."
claude --cloud "Execute docs/tasks/T03-store.md. Follow CLAUDE.md."
claude --cloud "Execute docs/tasks/T04-llm-layer.md. Follow CLAUDE.md."
claude --cloud "Execute docs/tasks/T05-fixture-and-oracle.md. Follow CLAUDE.md."
```

**T15 (the repository layer)** is a Fable task if you turned usage credits on. Start it at claude.ai/code instead: choose the repository and the `codeatlas` environment, switch the model to Fable (the session's model menu, or `/model claude-fable-5-1` as the first message), then send `Execute docs/tasks/T15-repository-layer.md. Follow CLAUDE.md.` Without Fable, launch it from the terminal like the others:

```powershell
claude --cloud "Execute docs/tasks/T15-repository-layer.md. Follow CLAUDE.md."
```

Each command starts an independent cloud session and returns. Tomorrow, review the six pull requests: deep for T15, T01 and T02; light for T03, T04 and T05.

## If you fall behind

Steps 1 to 6 matter today. If T00 is not merged by tonight, launch Wave 1 tomorrow morning; the plan still fits, with Wave 3 a day tighter.
