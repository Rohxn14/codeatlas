# CodeAtlas

CodeAtlas takes a repository, in any mix of languages, and builds an honest map of it:
packages, files, symbols, calls, tests and change history, each fact labelled with how it
was found and how sure it is. It analyses code statically and never runs it.

This is the Day 0 scaffold: intake, discovery and the structural (tags) tier. Later tasks
add the deep Python and TypeScript adapters, the repository layer, the store, search, the
impact engine and the agent (see `docs/tasks/`).

## Install

```
python -m pip install -e ".[dev]"
```

Python 3.11 or newer. Works on Windows (PowerShell) and Linux.

## Use

```
codeatlas scan path/to/repo
codeatlas scan https://github.com/pallets/click
codeatlas scan https://github.com/pallets/click@8.1.7 --json
```

`scan` lists every file, detects its language and tier, extracts definitions and calls,
and prints a census per language. A URL is fetched with one blobless `git clone` into
`.codeatlas/repos/<owner>__<repo>/` and reused while the remote commit is unchanged.

Every file lands in a (language, tier) row. A file that cannot be parsed (binary,
minified, too large, unreadable) is counted as text with its reason, and each folder left
out (`node_modules`, `dist`, a symlink, a submodule) is listed once with its file count,
so nothing disappears silently.

## Tiers

| Tier | Languages | What you get |
| --- | --- | --- |
| deep | Python, TypeScript, JavaScript (T01, T02) | hand-written adapters and resolvers |
| structural | any grammar with a tags query: Python, TypeScript, TSX, JavaScript, Go, Java, Rust, C#, PHP, Ruby, C, C++, Scala, Lua, Swift, Elixir | definitions, owners of methods, name-level calls |
| text | everything else | one node per file, with the reason |

Until T01 and T02 merge, Python and TypeScript/JavaScript run at the structural tier.

## Limits

Set in `codeatlas.toml` (defaults shown there): 20,000 files, 1 MB per file, 300 seconds
per index. When one is reached, CodeAtlas stops, keeps what it has, and names the limit
under `limits_hit`.

## Develop

```
ruff check .
pytest -q
```

Read `CLAUDE.md` and `docs/contract.md` first. Explainers for each module live in
`docs/explainers/`.
