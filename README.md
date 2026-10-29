# CodeAtlas

CodeAtlas takes any public repository, in any mix of languages, and builds an honest map of it: packages, files, symbols, calls, tests and change history, each fact labelled with how it was found and how sure it is.

This is the scaffold (T00): intake, discovery and the structural tags tier. The store, search, impact engine and agent arrive in later tasks; see `docs/tasks/`.

## Install

Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
```

## Use

```powershell
codeatlas scan .                                    # a local folder
codeatlas scan https://github.com/pallets/click     # a public GitHub repository
codeatlas scan https://github.com/pallets/click@8.1.7 --json
```

`scan` prints a language census and, per language, the tier, nodes by kind, raw calls and files with parse errors. Every discovered file appears in exactly one row; skipped files are listed with their reason, and any limit reached is named.

A URL is fetched with one blobless `git clone` into `.codeatlas/repos/<owner>__<repo>/` and reused while the remote commit is unchanged. Nothing from a cloned repository is ever installed, imported or run.

## Tiers

| Tier | Languages | What you get |
| --- | --- | --- |
| deep | Python, TypeScript, JavaScript (from T01 and T02) | Hand-written adapters and resolvers |
| structural | Python, TypeScript, TSX, JavaScript, Go, Java, Rust, C#, PHP, C, C++, Ruby | Definitions and calls from tree-sitter tags queries |
| text | everything else | A searchable file node; the language is still named when known |

## Limits

`codeatlas.toml` in the directory you run from sets `max_files` (20,000), `max_file_bytes` (1 MB), `max_seconds` (300) and `max_history_commits` (2,000). When a limit is reached, indexing keeps what it has and records the limit in the snapshot.

## Develop

```powershell
ruff check .
pytest -q                 # tests marked `live` need the network and are skipped by default
pytest -q -m live
```

Read `CLAUDE.md` and `docs/contract.md` before changing code.
