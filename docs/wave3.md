# Wave 3: Tuesday, Nov 3

**Today**: merge the "Wave 2 review fixes" pull request, launch Wave 3 (three sessions, a fourth if the credit allows), and read the Wave 2 reviews at the end of each brief. The credit ends **Nov 5, 1:29 PM in Bangalore**, so Wave 3 is the last cloud wave.

## Wave 2: where it stands

All seven tasks are on main once the review-fixes pull request is merged (T10 had no pull request; its branch is merged by that one). The review ran seven reviewers in parallel, one per task; findings are at the end of each brief. Everything they marked must-fix is fixed, with tests, one commit per task:

| Task | Must fix (done) |
| --- | --- |
| T06 Python resolver | `class Foo(Foo.Base)` recursed forever and dropped every Python edge of the repository |
| T09 Agent | `get_imports` missed every importer, because imports point at symbols |
| T10 Eval harness | three "caught" mutants were syntax errors; truth regenerated |
| T16 Structural | repeated, commented Python definitions still had different keys in the two tiers |
| T18 Pipeline report | folders discovery never entered vanished from the report and viewer |

Plus the larger should-fixes: T07 no longer guesses built-in methods (`push`, `map`, `get`: 83% of its name guesses on real code), T08's graph hop can now change the top results, T16 caps untyped fan-out at 5, resolvers get the checkout path (tsconfig works for GitHub URLs), and JavaScript files in `test/` folders count as tests.

**Main was broken for a while**: T07 and T16 each added `test_resolver.py`, and pytest cannot collect two test files with one name. Fixed in #26; CLAUDE.md now asks for unique test names.

## The acceptance suite, first real numbers

`eval/results/suite_20261103.md`: 47 pinned repositories, from `slugify` to `linux` and `TypeScript`, 20+ languages.

| Measure | Value |
| --- | --- |
| Repositories completed | 47 of 47 (no crash, no build problem) |
| Files | 69,762 (deep 9,150, structural 15,862, text 44,750) |
| Raw calls resolved | 57% (530,174 of 927,730); 0% in yesterday's run, before the resolvers |
| Time | 181 s for all 47 builds; the slowest is TypeScript at 63 s, which hits the 20,000-file limit |
| Peak memory | 514 MB |

Resolved share by declared language (an average over the repositories using it): Go 0.72, C# 0.69, Python 0.62, C 0.61, Swift 0.54, Java 0.50, C++ 0.50, PHP 0.46, Lua 0.45, TypeScript 0.42, Rust 0.42, Ruby 0.41, Elixir 0.33, JavaScript 0.22, Scala 0.14.

What these numbers say:

- **JavaScript is the weakest deep language.** Express went from 1% to 13% resolved after the test-folder fix; most of the rest are chains on untyped values (`request(app).get('/').expect(200)`) and prototype methods, which no static resolver of this kind sees. Worth a decision after Nov 4: type hints from JSDoc, or a precise layer.
- **C#, PHP and Ruby are name guesses only** until T17a. Their numbers are the "before" for T17a's pull request.
- **"Resolved" is not "right."** It counts raw calls with an edge; precision is measured only on the fixture and against SCIP. Q6 in `docs/decisions.md` asks exactly this.
- 5,125 files had parse errors, mostly deliberate syntax tests in `TypeScript` and generated C in `linux`. They keep their nodes, with the errors recorded.

## Launch Wave 3

After merging the pull request:

```powershell
git switch main; git pull
claude --cloud "Execute docs/tasks/T11-http-linker.md. Follow CLAUDE.md."
claude --cloud "Execute docs/tasks/T12-impact-engine.md. Follow CLAUDE.md."
claude --cloud "Execute docs/tasks/T17a-csharp-php-ruby.md. Follow CLAUDE.md."
```

Optional, only if the balance allows a fourth session:

```powershell
claude --cloud "Execute docs/tasks/T17b-c-cpp-rust.md. Follow CLAUDE.md."
```

| Task | Builds | Why now |
| --- | --- | --- |
| T11 | Cross-language HTTP linker: ROUTE nodes, HANDLES, CALLS_HTTP | The only labelled edges no task produces yet (fixture: 3 HANDLES, 6 CALLS_HTTP) |
| T12 | Impact engine and test selection, scored on mutation truth and held-out commits | The project's main promise; the agent's `impact` tool switches to it |
| T17a | C#, PHP and Ruby profiles through the add-language skill | Tests the skill; three languages leave name guesses |
| T17b (optional) | C, C++ and Rust profiles | Same procedure; easy to do locally if the credit runs short |

**Model choice**: if you want Opus for some sessions, start them at claude.ai/code with Opus picked, or send `/model opus` first. T12 benefits most from it; T11 next.

**File overlap**: none between T11, T12 and T17a. T17a and T17b both edit the profile registration and the structural explainer, so if you run both, merge T17a first and ask T17b's session to rebase.

## Decisions waiting for you

In `docs/decisions.md`: D-11 to D-21 (applied, reversible), and two new ones:

- **D-22** typed receivers at `SELF_METHOD` 0.9 in both deep languages (T06 does this; T07 does not yet).
- **D-23** no TESTS edges from name guesses (applied on Nov 3, while you delegated; one commit, reversible).

And Q2 (the name-guess cut-off: every resolver uses 5) and Q3 (whether weak signals add up: T12 will use your answer, or "highest signal" if there is none).

## After Wave 3

T14 (the scoreboard report) needs no cloud session: the suite runs in three minutes, so it can be re-run after each merge, locally or here. The local phase starts Nov 5: teleport any unfinished session first (`claude --teleport`).
