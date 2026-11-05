# Day 2: Saturday, Oct 31

**By tonight**: Wave 1 is fixed and merged, the pipeline (T18) is merged so you can index and view a real repository yourself, the plans for T06, T07 and T16 are reviewed, and four sessions (T06, T07, T16, T08) run overnight.

**Today's agent skill**: planning. Three sessions write a plan and stop; you review the plans before any code exists, which is the cheapest moment to change direction.

## Day 1: verified

| Item | State |
| --- | --- |
| Contract typed and on main | Done; CI green on main |
| Cloud environment | Done; the Gemini failure in the cloud was Google capacity (503), not your key (T04's live test) |
| T00 reviewed and merged | Done (PRs #2 and #3); the follow-up fix is PR #4 |
| Wave 1 | All seven pull requests (#4 to #10) open with green CI; each reviewed; findings at the end of each brief; one fix issue each (#11 to #17) |
| D-10 (scip-python on Linux only) | Pushed; your retry worked (`7b43cf9` on main) |
| Home folder `.git` | Renamed to `.git-disabled`, so tests no longer see a parent repository |
| Q1 to Q6 in `docs/decisions.md` | **Open.** Q2 is needed today: T06 and T07 use your answer for the name-guess cut-off |
| Learning log | **Open.** The T00 entry is empty; four lines per merge |

So Day 1 is complete except your two writing items. Both fit into today's step 3.

## Your four hours

| # | Step | Who | Time |
| --- | --- | --- | --- |
| 1 | Merge the review pull request; skim the review sections | You | 15 min |
| 2 | Paste the seven fix issues into their sessions | You, then cloud sessions | 15 min |
| 3 | While they run: decisions D-11 to D-19, the contract text, Q1 and Q2 | You | 45 min |
| 4 | Read `LABELS.md`, the fixture's answer key | You | 20 min |
| 5 | Merge Wave 1 in order | You | 40 min |
| 6 | Launch T18 (build) and T06, T07, T16 (plan only) | Cloud sessions | 10 min |
| 7 | Review the three plans | You | 45 min |
| 8 | Review and merge T18; index and view a real repository | Reviewer, then you | 30 min |
| 9 | Approve the plans; launch T08 | Cloud sessions | 10 min |

## 1. Merge the review pull request

The pull request "Day 1 review and Day 2 plan" adds a **Review** section at the end of each Wave 1 brief (`docs/tasks/T00` to `T05`, `T15`), this plan, five Wave 2 briefs, and proposed decisions. It touches only `docs/` and one line of `CLAUDE.md`, so it conflicts with nothing. Merge it on GitHub, then:

```powershell
git switch main; git pull
```

Each review section has the same parts: verdict, a checks table, must fix, should fix, **Your decisions** (the session's questions with a recommendation each), **Try it yourself** (commands you can run once the branch is checked out) and **Read these yourself**. Every pull request is "merge after fixes"; none needs to be sent back.

## 2. Paste the fix issues

Each issue starts with a link to its session and a line; paste everything below the line into that session. Read issues #13, #14 and #16 first: each has a part marked as your decision (D-11, D-17, D-12). Delete that part before pasting if you decide against it.

| Issue | Pull request | Size | Note |
| --- | --- | --- | --- |
| #11 | #4 T00 fix | small | |
| #12 | #5 T03 store | small | |
| #13 | #6 T01 Python adapter | medium | part 2 is D-11 |
| #14 | #7 T04 LLM layer | medium | part 5 is D-17 plus two small changes |
| #15 | #8 T02 TypeScript adapter | medium | part 0 rebases after #6 merges |
| #16 | #9 T15 repository layer | medium | part 5 is D-12; this pull request has no session link, so find the session in claude.ai/code by its title |
| #17 | #10 T05 fixture and oracle | medium | part 0 removes T15's commit from this branch; part 1 is the scip-python Windows refusal |

Each session pushes to its own branch, adds `Fixes #<issue>` to its pull request, and CI runs again. Merging the pull request closes the issue.

## 3. Decisions, contract text, Q1 and Q2

Open `docs/decisions.md`, section "Proposed on Oct 30". Nine proposals, each with why and what it affects. Write your call next to each. For the ones you accept, paste the contract text under it into `docs/contract.md` (section 4, 5 or 6 as marked). None changes `models.py`. Move the accepted ones into the Decided table.

Then answer Q1 and Q2 in the same file. Q2 decides when a name guess gives up; the T06, T07 and T16 plans will read it. Commit and push:

```powershell
git add docs
git commit -m "docs: decisions D-11 to D-19, contract text, Q1 and Q2"
git push
```

## 4. Read `LABELS.md`

`eval/fixtures/polyglot_app/LABELS.md` (until PR #10 merges, read it in the pull request's Files tab on GitHub, or locally after `gh pr checkout 10`) is the answer key T06 and T07 will be scored against, and it counts as truth only after you have read it. About 250 lines. For each rule, ask: would I label it this way? Two rules surprised the reviewers and became decisions (D-11 decorators, D-14 nested functions). Write any disagreement as a one-line comment on PR #10 before it merges.

## 5. Merge Wave 1 in order

Merge each pull request once its fix session has finished and CI is green, in this order (a trial merge of all seven in this order found one conflict, in #8):

1. **#4** T00 fix
2. **#5** T03 store
3. **#7** T04 LLM layer
4. **#9** T15 repository layer
5. **#10** T05 fixture and oracle (no longer depends on #9 after issue #17 part 0)
6. **#6** T01 Python adapter
7. **#8** T02 TypeScript adapter: it now conflicts in `registry.py`. Send its session: "PR #6 is merged. Do part 0 of the issue now: rebase onto origin/main, keep all four DEEP_ADAPTERS entries, run pytest -q and ruff check ., and push with --force-with-lease." Merge when CI is green.

Use squash merge, as before. After the last one:

```powershell
git switch main; git pull
pip install -e ".[dev]"
pytest -q
codeatlas scan tests/data/python        # python is now deep
codeatlas scan tests/data/typescript    # typescript, tsx and javascript are deep
```

Then run one **Try it yourself** block from a review you found interesting (T04's "pong" through both providers is the most satisfying), and fill in the learning log: one entry for T00, one for Wave 1.

## 6. Launch T18, and the three plans

```powershell
git switch main; git pull
claude --cloud "Execute docs/tasks/T18-pipeline-and-viewer.md. Follow CLAUDE.md."
claude --cloud "Execute docs/tasks/T06-python-resolver.md, phase 1 only: write the plan, open the draft pull request, and stop. Follow CLAUDE.md."
claude --cloud "Execute docs/tasks/T07-typescript-resolver.md, phase 1 only: write the plan, open the draft pull request, and stop. Follow CLAUDE.md."
claude --cloud "Execute docs/tasks/T16-structural-framework.md, phase 1 only: write the plan, open the draft pull request, and stop. Follow CLAUDE.md."
```

T18 needs everything from Wave 1 on main, so launch it only after step 5. If some Wave 1 pull requests are still open, launch the three plans anyway; they only read code.

## 7. Review the three plans

Each arrives as a draft pull request with `docs/plans/Txx.md`. For each plan, answer five questions:

1. Trace three labelled edges from `LABELS.md` through the plan. Does each come out right?
2. Can you say each resolution level's rule in one sentence? If not, ask the session to rewrite it until you can.
3. Do T06 and T07 answer "typed receivers" and the name-guess cut-off the same way? Make them agree.
4. Which mistake would the planned tests not catch?
5. Does the plan touch any file outside its brief?

Write your reply as one message per session, but **send it in step 9**, once T18 is merged:

> Approved, with these changes: 1. ... 2. ... T18 is merged: run `git pull origin main`, then build phase 2.

## 8. Review and merge T18

T18 is the piece you have been missing: after it, you can see results. Review it with the reviewer agent (in a local `claude` session: "Use the reviewer agent on PR #<number>", or ask me), fix what matters through its session, merge, then try it:

```powershell
git switch main; git pull
codeatlas index https://github.com/pallets/click
codeatlas view
python scripts/score_fixture.py
```

`view` opens the graph of click in your browser. Until the resolvers merge, you will see files, symbols, containment, packages, test pairings and co-change, but no calls: `score_fixture.py` shows CALLS recall near zero. Tomorrow, after T06 and T07, the same commands show the calls appear. Keep today's output to compare.

## 9. Approve the plans and launch T08

Send the three replies from step 7. Then:

```powershell
claude --cloud "Execute docs/tasks/T08-hybrid-search.md. Follow CLAUDE.md."
```

T06, T07, T16 and T08 run overnight.

## Credit: $60 left

Wave 1's seven sessions cost about $17 ($77 down to $60), about $2.50 each. Wave 2 sessions do more, so plan on $3 to $5 each.

| When | Sessions | Estimate |
| --- | --- | --- |
| Day 2 | 7 review fixes | $5 to $8 |
| Day 2 | T18, T06, T07, T16, T08 | $15 to $25 |
| Day 3 (Sun Nov 1) | T09 agent and MCP, T10 eval harness, T11 HTTP linker, and fixes | $10 to $15 |
| Day 4 (Mon Nov 2) | T12 impact engine, T17a (C#, PHP, Ruby), and fixes | $8 to $12 |
| Total | | $38 to $60 |

Check the balance after each wave. If it runs short, cut in this order: T17a, then T11, then the QA part of T10; all three can be done locally. T17b (C, C++, Rust, Kotlin) and T14 (the first acceptance-suite scoreboard) are planned for the local phase, or for Nov 4 if credit remains. The credit ends Nov 4, 11:59 PM Pacific: **Nov 5, 1:29 PM in Bangalore**.

## The days after

| Day | Review | Launch | Agent skill |
| --- | --- | --- | --- |
| Day 3, Sun Nov 1 | T06, T07, T16, T08 (deep for the resolvers and T16) | T09, T10, T11 (briefs written together in the morning) | Skills: you add one language yourself with T16's add-language skill |
| Day 4, Mon Nov 2 | T09, T10, T11 | T12, T17a | Hooks and CI |
| Day 5, Tue Nov 3 | T12, T17a | Whatever the credit allows | MCP: CodeAtlas inside Claude Code in VS Code |
| Wed Nov 4 | The last merges | Teleport any unfinished session to your laptop before the credit ends | Evaluating agents: with and without CodeAtlas on 10 questions |

## Teleport

`claude --teleport` pulls a cloud session down to your laptop: it checks out the session's branch in your local folder and loads the whole conversation into a local Claude Code session, which then carries on with everything the cloud session knew. Run it without an id to pick from a list, or with the session's id; inside Claude Code, `/teleport` (or `/tp`) does the same.

It needs a clean working tree (commit or stash first), the same repository, the session's branch pushed, and the same claude.ai account. From then on the work is local: it uses your plan's usage, not the cloud credit, and you push it yourself. Do not keep working in the cloud copy too, or the two will drift apart.

Three uses in this project:

1. **See a pull request work, with its author at hand.** Teleport the T18 session, run `codeatlas view` on your machine, and ask the session that wrote it why step 6 works the way it does. It remembers every choice.
2. **Windows-only bugs.** When something fails only on Windows (like the git-parent bug of Day 1), teleport the session that wrote the code and fix it where the bug reproduces, instead of describing it to a cloud session that runs on Linux.
3. **After Nov 4.** Any session still unfinished when the credit ends can be teleported and finished locally, so no work is lost.

## If you fall behind

- **Fixes not back by midday**: merge whatever is green, in the order above. T18 needs #4, #5, #6, #8, #9 and #10 on main; T04 (#7) can merge later.
- **T18 not merged tonight**: send the plan approvals and launch T08 tomorrow morning instead. Day 3 still works, a little tighter.
- **A plan needs a big change**: say so in your reply and ask for a revised plan before building. One more round costs little; building the wrong resolver costs a session.
