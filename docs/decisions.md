# Decision log

Every design decision lands here: the question, the decision, and why. When a pull request asks "Questions for the owner", the answers go here too.

## Decided

| # | Decision | Why | Date |
| --- | --- | --- | --- |
| D-01 | SQLite plus a NetworkX view; no graph database | Nothing to run on Windows or in the cloud VM; you write the traversals yourself | 2026-10-28 |
| D-02 | tree-sitter for every language, including Python | One approach for every language, and it tolerates syntax errors | 2026-10-28 |
| D-03 | Three tiers per file: deep (Python, TS/JS), structural (tags, imports and resolution profiles), text | Coverage everywhere, depth where there is a benchmark | 2026-10-28, renamed 2026-10-29 |
| D-04 | Every edge records how it was resolved and a confidence | Impact ranking and an honest UI both depend on it | 2026-10-28 |
| D-05 | Static analysis only; the eval harness alone runs tests, for pinned benchmark repos | Public repositories are not safe to execute | 2026-10-29 |
| D-06 | Accept a public GitHub URL through a blobless clone, with file, size and time limits | Avoids GitHub API rate limits; keeps history for co-change without old file contents; keeps huge repos from stalling the indexer | 2026-10-29 |
| D-07 | Repository-first: every repository gets a repository layer (packages, tests, co-change) whatever its languages; depth grows per language | The owner's requirement: any public repository must work. "Works" means four promises measured on a suite of about 40 repositories | 2026-10-29 |
| D-08 | Strategy memory moves to the local phase | Frees cloud sessions for the repository layer and more languages; it belongs with AdaptiveAgent anyway | 2026-10-29 |
| D-09 | The MCP server is built with the agent tools in T09 | Same tools, one extra entry point; lets the owner practise giving an agent his own tools | 2026-10-29 |

## Open: Day 1 and 2 questions

Answer in a few sentences each. Wrong answers are fine; unexamined ones are not.

### Q1. Why do nodes have both `key` and `id`?

Explain in one sentence, then name one feature that would break if we stored only `id`.

Your answer:

### Q2. Name guesses across languages (decide before Wave 2)

In Python, `obj.save()` has an unknown type. `save` is defined in two Python classes and one TypeScript class, and the caller's file imports neither Python class's module. How many candidates does the guess get, at which resolution level, and with what confidence? The contract keeps name guesses inside one language: give one real case where a candidate in another language would be the right answer, and say which part of CodeAtlas should catch it instead.

Your answer:

### Q3. Many weak paths vs one path (decide before Wave 3)

The impact engine scores a function by its best path: two hops at 0.9 and 0.5 give 0.45. A function reachable by three separate paths of 0.4 each scores only 0.4. Should more paths raise the score? Write a formula, then one case where your formula gives the wrong answer.

Your answer:

### Q4. When the tests miss a real break

Our impact "truth" is the set of tests that fail after a mutation. What happens to measured precision and recall when a mutation breaks real behaviour but no test notices? What would you record so this neither flatters nor punishes the impact engine?

Your answer:

### Q5. When co-change lies (decide before T12 in Wave 3)

Git history says `a.py` and `b.py` changed together in 30 of the 40 commits that touched `a.py`, a confidence of 0.75. Name two situations where that is not a real dependency, and how you would filter each. Then name one real dependency your filter would wrongly throw away.

Your answer:

### Q6. "Works on any repository" in three numbers

Write the three numbers you would put at the top of the README to show that CodeAtlas works on any repository. Which of the three could look good while the product is actually bad, and what would you pair it with?

Your answer:
