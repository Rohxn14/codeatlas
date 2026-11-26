# How often are CALLS edges right? click, Nov 27, 2026

The first measurement of precision on a real repository. Until now precision was known
only on the fixture, which was written for the tool (1.0).

- **Snapshot**: click@2247b35ea1c4, the acceptance suite's pinned commit.
- **Sample**: `python scripts/sample_precision.py sample`, seed 27: 20 CALLS edges each for
  direct, self-method, import-scoped and name-guess edges, 10 for calls to something outside
  the repository. Every row is in `precision_click_20261127.json`, with the line of code,
  the call as written, the target, and the label's reason.
- **Rule**, fixed before labelling: an edge is right if this call can run that function in
  some real execution of the code; wrong if it cannot.
- **Labelled by** Claude Code, reading the code at each line. Not by hand: check any row.

| stratum | right | precision | 95% interval | mean confidence | edges |
| --- | --- | --- | --- | --- | --- |
| direct | 20/20 | 1.00 | 0.84-1.00 | 1.00 | 2,073 |
| self_method | 20/20 | 1.00 | 0.84-1.00 | 0.90 | 274 |
| import_scoped | 6/20 | 0.30 | 0.15-0.52 | 0.45 | 1,002 |
| name_guess | 5/20 | 0.25 | 0.11-0.47 | 0.22 | 989 |
| external | 10/10 | 1.00 | 0.72-1.00 | 1.00 | 1,613 |

Weighted by the edges in each stratum, about 76% of all CALLS edges are right.

**Reading it**

- Edges found from what the code says (a name bound by an import, `self`, a declared type,
  a builtin) were right 50 times out of 50.
- **Name guesses are calibrated**: right 25% of the time, at a mean confidence of 0.22.
- **Import-scoped edges are over-confident**: right 30% of the time at a mean of 0.45, and
  2 of the 5 at confidence 1.0 were wrong (#43: `runner.invoke` sent to a class's
  `invoke` in the same test file; #45: a `threading.Thread`'s `start` sent to a test
  helper).
- **One pattern explains most wrong edges**: 27 of the 90 rows are `runner.<method>(...)`
  and only 6 of them are right. `runner` is a pytest fixture that returns `CliRunner()`,
  and the resolver cannot know its type. Other wrong edges are local variables made by a
  constructor (`opt = click.Option(...)`).
- Across all of click, **819 of the 1,991 guessed edges (41%)** have such a receiver: 660
  set by the `runner` fixture, 159 by a local constructor. The T06 plan left locals out
  (decision 2) because "IMPORT_SCOPED usually finds `Foo.run` anyway"; on click it is
  right 30% of the time.

**Limits**: one Python repository; 20 rows per stratum, hence the wide intervals; CALLS
edges only; labels by a model, with their reasons, not by a person.
