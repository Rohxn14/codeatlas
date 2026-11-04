# Demo: CodeAtlas on pallets/click

One end-to-end run on a real public repository from `eval/suite/repos.yaml`, on 2026-11-04
in a Linux cloud session. Output is pasted as printed and trimmed where marked `...`.

## Fetch

A shallow clone with two commits, so that `HEAD~1` exists for the impact step. (Indexing a
URL makes a blobless clone with full history, so `HEAD~1` would exist there too; `--git`
on such a snapshot may fetch old file contents over the network. Cloning by hand keeps the
demo small and offline after the clone.)

```
$ git clone --depth 2 https://github.com/pallets/click
$ cd click && git log --oneline -1
2247b35 Add `Parameter.spec` and deprecate `human_readable_name` (#3877)
$ git diff --stat HEAD~1
 CHANGES.md                 |  13 +++++
 docs/parameters.md         |  46 ++++++++++++----
 docs/upgrade-guides.md     |   3 +-
 src/click/core.py          | 133 +++++++++++++++++++++++++++++++++++++++++----
 tests/test_arguments.py    |  30 ++++++++++
 tests/test_deprecations.py |  36 ++++++++++++
 tests/test_options.py      |  31 ++++++++++-
 7 files changed, 266 insertions(+), 26 deletions(-)
```

The first attempt picked `itsdangerous`, but its newest commit only edits a workflow
file, which has no symbols to follow; `requests` was the same. `click`'s newest commit
changes real code and its tests.

## Index

```
$ codeatlas index . --db ../click.db
CodeAtlas 0.1.0: click@2247b35ea1c4
source: .

Files by language and tier
language  files
--------  -----
bash          1
ini           1
json          1
markdown     42
python       91
text         22
toml         11
yaml          9
total: 178 files (deep: 91, text: 87); skipped: 2

Nodes: class 181, external 325, function 1291, module 178, package 11, test 606
Edges: 10256
  by kind: calls 5951, contains 2256, depends_on 10, imports 671, inherits 148, tests 1220
  by resolution: convention 5, direct 4179, import_scoped 1715, name_guess 989, self_method 283, structural 3085
  dropped: duplicate (merged into one) 40
Raw calls: 7278, resolved 5772, unresolved 1506 (python 1506)
Problems:
  files with parse errors: 0
Seconds: intake 0.007, discover 0.016, parse 0.624, repo_layer 0.015, write 0.22, resolve 0.126, link 0.002, total 1.012
limits hit: none
```

## Search

```
$ codeatlas search "parse a boolean flag value" --db ../click.db -k 8
  1  0.0164  test      tests/test_options.py::test_hide_false_default_boolean_flag_value  tests/test_options.py:1622  [bm25]
  2  0.0161  test      tests/test_options.py::test_show_true_default_boolean_flag_value  tests/test_options.py:1605  [bm25]
  3  0.0159  test      tests/test_options.py::test_boolean_flag_envvar  tests/test_options.py:529  [bm25]
  4  0.0156  test      tests/test_options.py::test_show_default_boolean_flag_name  tests/test_options.py:1587  [bm25]
  5  0.0154  test      tests/test_options.py::test_flag_group_competition_non_boolean  tests/test_options.py:3368  [bm25]
  6  0.0152  test      tests/test_basic.py::test_boolean_flag  tests/test_basic.py:317  [bm25]
  7  0.0149  function  tests/test_basic.py::test_boolean_flag.cli  tests/test_basic.py:331  [bm25]
  8  0.0147  function  tests/test_options.py::test_boolean_flag_envvar.cli  tests/test_options.py:595  [bm25]
note: no embeddings for this snapshot: BM25 only
```

BM25 alone favours test names, which repeat the query's words. `--embed` would add the
vector ranking; it was not run here, to avoid the model download.

## Impact of the newest commit

```
$ codeatlas impact --git HEAD~1 --db ../click.db --top 10
snapshot click@2247b35ea1c4: 7 changed files, 45 changed symbols
changed: CHANGES.md::, docs/parameters.md::, docs/upgrade-guides.md::, src/click/core.py::_echo_aborted, src/click/core.py::, src/click/core.py::_outside_click_stacklevel, src/click/core.py::Parameter, src/click/core.py::Parameter.__init_subclass__, src/click/core.py::Parameter.__init__, src/click/core.py::Parameter._check_name_is_usable and 35 more

525 targets, top 10 shown
  1  0.800  module    src/click/__init__.py::
       graph 0.800: src/click/core.py::Argument <-imports 1- src/click/__init__.py::
  2  0.800  function  src/click/core.py::Command.parse_args
       graph 0.800: src/click/core.py::Parameter.handle_parse_result <-calls 1- src/click/core.py::Command.parse_args
  3  0.800  function  src/click/core.py::Option._check_name_is_normalized
       graph 0.800: src/click/core.py::_outside_click_stacklevel <-calls 1- src/click/core.py::Option._check_name_is_normalized
  ...
  9  0.800  test      tests/test_arguments.py::test_argument_get_help_record_never_none
       graph 0.800: src/click/core.py::Argument.__init__ <-calls 1- tests/test_arguments.py::test_argument_get_help_record_never_none
 10  0.800  test      tests/test_arguments.py::test_argument_name_check_applies_when_not_exposed
       graph 0.800: src/click/core.py::Argument.__init__ <-calls 1- tests/test_arguments.py::test_argument_name_check_applies_when_not_exposed

warnings (3):
  CHANGES.md has no symbols (markdown); using the file
  docs/parameters.md has no symbols (markdown); using the file
  docs/upgrade-guides.md has no symbols (markdown); using the file
```

## Tests to run

```
$ codeatlas tests --git HEAD~1 --db ../click.db --top 8
snapshot click@2247b35ea1c4: 7 changed files, 45 changed symbols
...
472 tests, top 8 shown
  1  1.000  module    tests/test_arguments.py::
       changed 1.000: tests/test_arguments.py::test_deprecated_empty_help_no_leading_space (the change edits this test)
  2  1.000  test      tests/test_arguments.py::test_deprecated_empty_help_no_leading_space
       changed 1.000: tests/test_arguments.py::test_deprecated_empty_help_no_leading_space (the change edits this test)
  ...
  6  1.000  module    tests/test_deprecations.py::
       changed 1.000: tests/test_deprecations.py::test_isolated_filesystem_deprecated (the change edits this test)
  ...

test files to run (score >= 0.3): 52 of 55; skipped share 5%
  tests/test_arguments.py
  tests/test_deprecations.py
  tests/test_options.py
  tests/test_basic.py
  tests/test_command_decorators.py
  tests/test_context.py
  tests/test_formatting.py
  tests/test_info_dict.py
  ... and 44 more (see --json)
```

This is the hub case from `docs/explainers/impact.md`: the commit edits `Parameter`, the
base class every option and argument goes through, so nearly every test reaches it in a
hop or two and only 5% of test files can be skipped. The edited tests themselves come
first at score 1.0.

## Ask

```
$ codeatlas ask "What does Parameter.spec return, and which callers use it?" --db ../click.db --max-steps 8
groq try 1/3 failed: groq failed (429): ... Rate limit reached for model `openai/gpt-oss-20b` ... on tokens per minute (TPM): Limit 8000, Used 6802, Requested 2782 ...
...
gemini try 1/3 failed: gemini failed (504): 504 DEADLINE_EXCEEDED ...
gemini try 2/3 failed: gemini failed (503): 503 UNAVAILABLE. ... This model is currently experiencing high demand ...
...
codeatlas: the language model could not be reached: every provider failed: ...
```

Exit code 1. The session's proxy supplied the keys, but both attempts (the fixture
question earlier and this one) hit Groq's free-tier limit of 8,000 tokens per minute and
Gemini's overload errors, so no answer is shown. The first request alone is about 3,000
tokens (system prompt plus tool schemas). The trajectory file was still written.
