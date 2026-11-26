# Results

Scores written by eval runs, one file per run, named by date and what was measured, so
progress can be compared over time.

## Nov 26-27, 2026: checkpoint 7, everything measured again

Run on the owner's Windows laptop; the runs before were on a Linux cloud machine, so
**seconds are not comparable**, and peak memory reads `n/a` (it comes from Python's
`resource` module, which Windows does not have).

| File | What |
| --- | --- |
| `suite_20261126.md`, `.json` | the acceptance suite: 46 of 47 repositories, all completed |
| `impact_mutants_20261126.md` | test selection on the two mutation benchmarks |
| `impact_cochange_20261126.md` | predicting co-changing files on held-out commits (click, cobra, express) |
| `search_20261126.md` | search on the fixture's 15 questions, with the real bge-small model |

**Against the Nov 3 suite (`suite_20261103_wave3`), same pinned commits:**

- **Resolution did not move.** Leaving TypeScript out (below), 45 repositories: 873,326 raw
  calls before, 882,204 now; resolved share 51.2% before, 51.3% now. Per repository the
  share is unchanged except nlohmann_json (46% to 48%) and fmt (44% to 43%), the C and C++
  scopes of T21, which also explain most of the 6% more CALLS edges.
- **New edges come from the features added since:** CONTAINS 174,700 to 262,080
  (documentation sections and the parts of text files), REFERENCES 0 to 76,728 (D-62).
- **One finding about REFERENCES:** Alamofire, 571 files, has 53,513 of them, 84% of its
  edges. Its `docs/` is a generated site: 332 pages, each with a sidebar naming about 164
  others (53,018 of the 53,513 edges). Every edge is true, and almost none says anything. Not changed: what
  should count is the owner's decision.
- **TypeScript did not fit the suite's 300 seconds.** Since every file is read (#81), it
  has 68,192 files instead of the 20,000 it stopped at before, and listing them used the
  budget: 23 files were parsed. Indexed alone with the app's limit of one hour it
  completes: 970 s, 581,674 edges, 61% of 375,841 calls resolved, 12,690 files with parse
  errors. Of the 970 s, discovery took 694. With the files in the operating system's cache,
  the same discovery takes 19 s, so the cost is reading files from disk, not discovery's own
  work.
- **linux was not run:** it has no clone here, and a blobless clone is several GB.
  `python -m eval.suite --only linux` runs it.

**Impact, co-change and search did not move:** test selection F1 0.839 and 0.838 (64% and
46% of test files skipped); recall@10 on held-out commits, history against the engine,
click 0.387 against 0.294, cobra 0.497 against 0.477, express 0.677 against 0.530. New in
this table: on cobra, "files in the same folder" scores 0.520 and beats both. Search
recall@5 is as on Nov 16 (vectors 0.733, fused 0.600); MRR rose a little wherever BM25
takes part (BM25 0.164 to 0.208), and the change that did it was not traced.

## Nov 27, 2026: precision of CALLS edges on click

`precision_click_20261127.md` and `.json`: the first measurement of how often edges are
right on a real repository, from 90 sampled edges labelled against the code
(`scripts/sample_precision.py`). About 76% of click's CALLS edges are right; guesses whose
receiver comes from a pytest fixture or a local constructor make most of the wrong ones.
