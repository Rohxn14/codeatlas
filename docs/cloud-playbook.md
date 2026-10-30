# Cloud playbook: launching, spending and reviewing

The bonus credit pays for cloud sessions until Nov 4, 11:59 PM Pacific (1:29 PM IST on Nov 5). After that, the same briefs run locally on your normal plan.

## 1. Launch

1. **Push first.** A cloud session clones the GitHub copy of your current branch, not your local folder. Uncommitted or unpushed work is invisible to it.
2. **Pick the environment once**: in a local `claude` session, run `/remote-env` and choose `codeatlas`. CLI-launched sessions then use it.
3. **Launch one session per brief.** At claude.ai/code: choose the `codeatlas` repository, the `main` branch and the `codeatlas` environment, keep the default model, and send `Execute docs/tasks/Txx-....md. Follow CLAUDE.md.` That is exactly what `claude --cloud` does from a terminal. One task gets one session and one pull request: never start a second session on a brief that already has an open pull request, and put follow-ups for a task (fixes, answers) in that task's own session. Or, from the VS Code terminal:

   ```powershell
   claude --cloud "Execute docs/tasks/T01-python-adapter.md. Follow CLAUDE.md."
   ```

   Running `claude` in the integrated terminal needs the standalone Claude Code CLI; the VS Code extension's panel uses its own bundled copy.
4. **Watch** at claude.ai/code, in the Code tab of the Claude mobile app, or in the VS Code extension under Session history → Remote. A session that asks a question waits for you; answer from any device and it carries on.
5. **Launch before you sleep.** Sessions keep running with your laptop closed, so a wave started at night is ready to review in the morning.

## 2. Spend the credit well

1. **One brief, one session, one pull request.** Never a vague prompt such as "build CodeAtlas".
2. **Batch feedback.** Each message makes Claude carry the whole conversation forward, so one message with ten comments costs less than ten messages with one each.
3. **Ask questions locally; send fixes to the cloud.** To understand a pull request, pull it into VS Code (section 3, step 4) and ask there on your normal plan. Use the cloud session only for changes.
4. **Plan the big tasks locally first** (T06, T07, T09, T12): in VS Code, use plan mode to agree the approach, commit it as `docs/plans/Txx.md`, then launch the session with "Execute docs/tasks/Txx-....md following docs/plans/Txx.md".
5. **Choose the model per task.** Fable is the strongest model you can pick in a cloud session, and the bonus credit pays for it, but it costs more per token, so the credit buys fewer sessions. On the Pro plan, choosing Fable also requires usage credits turned on with a balance, and once the bonus is spent Fable bills those credits pay-as-you-go. Before turning usage credits on, set a low monthly cap. Use Fable where reasoning decides quality (T06, T07, T12, T15, T16) and the default model for plumbing (T03, T04, T08, CI fixes). Run T00 on the default model first and note its cost, so you know the baseline.
6. **Launch plain sessions.** The bonus does not cover Claude Code Projects, Routines or chat.
7. **Check the budget after every wave.** Read the remaining balance in the usage menu, divide by the sessions left, and compare with what the last wave cost per session. If it does not fit, move tasks to the local phase in this order: T17b, then T17a (both follow the add-language skill and are easy to run locally), then T11. Switching a planned Fable task to the default model is the other lever.

## 3. Review loop

**Two depths.** Your review time sets the pace, at about four to six pull requests a day. Review **deep** (30 to 45 minutes, every step below) for code you will rewrite or must defend in an interview: resolvers, the repository layer, the structural framework, impact. Review **light** (10 to 15 minutes: steps 0 to 4 and 8) for plumbing: store, LLM layer, CI, harness.

0. **Let the reviewer subagent go first.** In VS Code, in a local `claude` session in the repo, ask: "Use the reviewer agent on PR #N." It downloads the pull request's branch with `git fetch` and reads the changes with git; it never talks to the cloud session. For it to run the tests, your `.venv` needs the project installed: `pip install -e ".[dev]"`, once T00 is merged. It checks scope, the contract, tests, a mutation spot-check, the explainer and safety, and suggests questions for you. It runs on your normal plan, not the credit. Read its report, then do your own review: it narrows where to look, it does not replace looking.
1. **Read the pull request description.** Every section of the template should be filled, especially "Questions for the owner" and "Contract change request".
2. **Check scope**: `git diff --stat main...origin/task/Txx-...`. Only files the brief allows, plus tests and the explainer.
3. **Read the explainer before the code.** Close it and say the What, Why, How and Where out loud. Whatever you cannot explain is your first question.
4. **Run it locally**:

   ```powershell
   git fetch origin
   git switch task/Txx-short-name
   pip install -e ".[dev]"
   pytest -q
   ```

   Or run `claude --teleport <session-id>` in the repo folder: it checks out the session's branch and loads its whole conversation into your terminal, so you can ask "why did you do X" locally. It needs a clean working tree, so commit or stash first.
5. **Break one thing on purpose.** Change one line in the main function (flip a condition, drop a branch) and run the tests. If nothing fails, the tests are weak: ask for a test that catches it. This is mutation testing by hand, the same idea the impact benchmark uses.
6. **Read the main function end to end.**
7. **Send feedback in one round, in the task's own session.** That session already knows the code, and it pushes fixes to the same pull request. In the session at claude.ai/code, open the Changes card, comment on lines in the diff view, and send all comments with your next message. Alternatively, review on GitHub with auto-fix turned on; auto-fix also runs as a cloud session, so it spends credit too.
8. **Merge**: squash merge on GitHub and delete the branch. Copy your answers to the "Questions for the owner" into `docs/decisions.md`.
9. **Log it**: three lines in `docs/learning-log.md`.

**Known conflict in Wave 1**: T01 and T02 both add an entry to `src/codeatlas/indexer/registry.py`. Merge one first; the second will conflict, and the fix is to keep both entries.

## 4. After Nov 4

- Run the same briefs locally: in the VS Code extension (Command Palette → Open in New Tab for each conversation), or `claude --worktree Txx` in separate terminals when two tasks change code at the same time, so each works in its own folder and branch.
- Local sessions use your normal plan limits, so run one or two at a time.
