# Wave 4: Wednesday, Nov 4

**Today**: launch Wave 4 (two sessions, a third if the balance allows), then read the Wave 3 reviews at the end of the T11, T12, T17a and T17b briefs. The credit ends **Nov 5, 1:29 PM in Bangalore**; this is the last cloud wave.

## Wave 3: where it stands

All seven pull requests are merged: T11 (#28), T17a (#29), T12 (#30), T17b (#31), and the three review-fix sessions T11f (#32), T17f (#33), T12f (#34). On main: 794 tests pass, and the fixture scores 165 of 165 labelled edges at precision 1.0. Every edge kind is now produced, including the 3 HANDLES and 6 CALLS_HTTP edges no task made before.

What the fix sessions changed, in one line each:

- **T11f**: the fixture's HTTP client calls went from 2 of 6 found to 6 of 6. Python `TestClient` instances and axios instances imported from another file are followed, and linker problems now reach the build report.
- **T12f**: a change to a Python route handler now reaches the TypeScript code that calls it. `parse_diff` handles renames, binary files and hunk lines starting with `---`. The co-change benchmark no longer leaks future structure.
- **T17f**: removed the wrong 1.0 edges in Rust, PHP, Ruby and C#, applied the 5-candidate cut-off everywhere, and made `Context.read` refuse paths outside the checkout.

**T12's honest result**: on test selection the engine beats every baseline. Its F1 is 0.84 on both benchmarks, against 0.52 and 0.72 for "run every test", and it skips 46-64% of test files. On predicting which files change together, it does **not** beat plain co-change history once the leak is removed. History's recall@10 is higher on click, cobra and express; the engine wins only on express precision. This is the most interesting open question for v2.

## Scoreboard: the acceptance suite after Wave 3

`eval/results/suite_20261103_wave3.md`, compared with this morning's `suite_20261103.md`. All 47 repositories completed both times.

| Measure | Before Wave 3 | After |
| --- | --- | --- |
| Raw calls | 927,730 | 1,130,634 |
| Resolved share | 57.1% | 54.9% |
| Time for all 47 | 181 s | 275 s |
| Peak memory | 514 MB | 470 MB |
| HANDLES edges | 0 | 23 |
| Build problems reported | 0 | 265 (all linker lines: unmatched HTTP calls by reason, inline Express handlers) |

The resolved share went **down**, and that is good news, for two reasons:

1. **More calls are seen.** C and C++ had no call queries before T17b. `linux` went from 780 raw calls to 39,827, `fmt` from 507 to 18,827 and `jq` from 272 to 9,920. Many more calls are resolved, but the denominator grew more.
2. **Fewer bad guesses.** T17f applied the 5-candidate cut-off to untyped receivers in every tier. `commons-lang` (Java) went from 159,461 CALLS edges to 45,735, so its "resolved" share fell from 95% to 79%. The edges that went were fan-outs of six or more candidates at confidence 0.17 or less. "Resolved" counts calls with any edge, not correct ones, and that is why Q6 in `docs/decisions.md` matters.

Average resolved share by declared language, before → after: Rust 0.42 → 0.53, C 0.42 → 0.50, C# 0.38 → 0.42, PHP 0.46 → 0.49, Ruby 0.41 → 0.43, Java 0.50 → 0.46 and C++ 0.50 → 0.45 (the cut-off), JavaScript unchanged at 0.22, TypeScript unchanged at 0.42. Biggest single gains: `jq` 0.41 → 0.66, `ripgrep` 0.35 → 0.52, `anyhow` 0.49 → 0.59.

No CALLS_HTTP edges across the suite: none of the 47 repositories has both a client and a server in one tree. The linker is measured on the fixture (6 of 6) and on the two repositories in T11's pull request.

## Launch Wave 4

Check your balance first. Sessions have cost about $3 to $5 each.

```powershell
git switch main; git pull
claude --cloud --model opus "Execute docs/tasks/T20-ts-typed-receivers.md. Follow CLAUDE.md."
claude --cloud "Execute docs/tasks/T19-cli-and-readme.md. Follow CLAUDE.md."
```

Optional, only if the balance allows a third session:

```powershell
claude --cloud "Execute docs/tasks/T21-generic-adapter-scopes.md. Follow CLAUDE.md."
```

| Task | Builds | Why now |
| --- | --- | --- |
| T19 | `codeatlas search`, `ask`, `impact`, `tests`, `mcp`; a new README; an end-to-end demo on a real repository | Everything works, but half of it has no command; the README still describes Day 0 |
| T20 | Typed receivers for TypeScript and JavaScript from annotations, class fields and JSDoc (finishes D-22) | JavaScript is the weakest deep language (22% resolved) |
| T21 (optional) | C/C++ calls credited to the function, not the file; C# nested namespaces | The impact engine cannot tell which C function a change reaches |

**Model**: T20 needs the most judgement (type resolution), so Opus. T19 is wiring and writing, so Sonnet is fine. After starting, type `/model` in the session to confirm what it runs on.

**File overlap**: none between the three.

## After Wave 4

The local phase starts Nov 5. Before 1:29 PM, teleport any session that has not finished (`claude --teleport`). The catch-up reading order is in my reply of Nov 3, in data-flow order: contract, T00, T15, T01, T02, T16, T06, T07, T03, T18, T11, T04, T08, T09, T12, T05, T10. For each task, read its explainer first, then the brief and its review.
