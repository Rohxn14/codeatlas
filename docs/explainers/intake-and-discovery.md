# Intake and discovery

Modules: `src/codeatlas/indexer/intake.py`, `src/codeatlas/indexer/discover.py`,
`src/codeatlas/config.py`, and the `scan` command in `src/codeatlas/cli.py`.

## What

**Intake** turns what the user typed into a folder on disk and a commit SHA. A local
path is used as it is. A public GitHub URL (`https://github.com/owner/repo`, optionally
`@ref`) is cloned once into `.codeatlas/repos/<owner>__<repo>/` and reused while the
remote still points at the same commit.

**Discovery** lists every file in that folder and returns a `FileRecord` for each one it
will analyse: repo-relative forward-slash path, language, tier, SHA-256 and size. Files it
will not analyse (binaries, minified bundles, files over the size limit, symlinks, files in
`node_modules`-style folders) go into a `skipped` list with the reason.

**Config** holds the limits: 20,000 files, 1 MB per file and 300 seconds per index by
default, plus `max_history_commits` (2,000) for the repository layer. When a limit is
reached, indexing stops, keeps what it has, and names the limit in `Snapshot.limits_hit`.

## Why

- **One `git clone`, never the REST API.** Unauthenticated GitHub API calls are limited to
  60 an hour; a repository with 500 files would take most of a day file by file. A clone is
  one request.
- **Blobless (`--filter=blob:none`) and single-branch.** The repository layer (T15) needs
  commit history for co-change, but not the contents of old files. A blobless clone brings
  every commit and tree, and file contents only for the checked-out commit. Rejected: a
  shallow clone (`--depth 1`), which is smaller but has no history at all.
- **Reuse by SHA, via `git ls-remote`.** `ls-remote` asks the remote which commit a ref
  points at without downloading anything. If it matches the clone's `HEAD`, the clone is
  reused. If not, the clone is deleted and made again. Rejected: `git fetch` into the
  existing clone, which is faster for big repositories but has awkward corner cases with
  single-branch blobless clones and changing refs; worth revisiting if re-clones get slow.
- **`git ls-files` when possible.** Inside a git work tree, git already knows exactly
  which files belong to the repository and applies every `.gitignore`, global excludes
  and `.git/info/exclude` correctly. Untracked files that are not ignored are included
  (`--others --exclude-standard`), so a local work in progress is scanned too. Outside git
  the code walks the folder and applies `.gitignore` files with `pathspec`, the same
  matching rules git uses.
- **No silent gaps.** A skipped file keeps its path and reason, and a file with an unknown
  extension is still a `text` record. The `scan` totals add up to every file seen.
- **Safety.** Intake runs only `git clone`, `git ls-remote` and `git rev-parse`, with
  prompts, LFS downloads and `core.fsmonitor` (a config hook that can run a program)
  turned off. The `@ref` is checked so it cannot start with `-` and be read as a git
  option. Nothing from the repository is executed.
- **Limits come from the tool's own `codeatlas.toml`**, never from the indexed
  repository, so a repository cannot raise its own limits.

## How

Intake (`open_source`):

1. If the text contains `://`, parse it as a URL: scheme must be `https`, host
   `github.com` (or `www.github.com`), no user, port, query or fragment, then
   `owner/repo[.git][@ref]`. Anything else raises `IntakeError`.
2. `git ls-remote <url> <ref> <ref>^{}` (or `HEAD`). The `^{}` line, if present, is the
   commit an annotated tag points at; it is preferred over the tag object itself.
3. If `.codeatlas/repos/<owner>__<repo>/.git` exists and its `HEAD` equals that SHA,
   reuse it. Otherwise delete the folder and run
   `git clone --filter=blob:none --single-branch --no-tags [--branch <ref>] -- <url> <dest>`.
4. A local path must be an existing folder; its SHA is `git rev-parse HEAD`, or `None`
   outside git (then `scan` uses a hash of all file hashes instead).

Discovery (`discover`), for each candidate path in sorted order:

1. Stop with `max_seconds` if the deadline has passed, or `max_files` if that many
   records already exist.
2. Skip with a reason: a folder named `node_modules`, `.venv`, `venv`, `dist`, `build`,
   `.git` or `.codeatlas` in the path; a symlink; a `*.min.js` file; a file over
   `max_file_bytes` (this also adds `max_file_bytes` to the limits hit); a NUL byte in the
   first 8 KB (binary).
3. Otherwise read the bytes, hash them, pick the language from the file name or
   extension, and ask the registry for the tier.

Worked example. A folder (not a git repository) containing:

```
.gitignore          -> "logs/"
app.py
web/App.tsx
web/vendor.min.js
logs/run.log
node_modules/x/index.js
README.md
```

The walk prunes `node_modules/` and, because of `.gitignore`, `logs/`. Discovery returns:

| path | language | tier |
| --- | --- | --- |
| `.gitignore` | text | text |
| `README.md` | markdown | text |
| `app.py` | python | structural |
| `web/App.tsx` | tsx | structural |

and `skipped = [("web/vendor.min.js", "minified")]`, `limits_hit = ()`. With
`max_files = 2` it would return the first two records and `limits_hit = ("max_files",)`.

## Where

- Contract types: `FileRecord`, `Tier` and `Snapshot` (`limits_hit`) from
  `codeatlas.models`; `make_snapshot_id` builds the snapshot id in `scan`.
- Discovery takes `tier_for` from `indexer/registry.py`, so a file's tier is what will
  really happen to it: a language whose grammar fails to load is reported as text.
- The repository layer (T15) reads `max_history_commits` and the clone's history; the
  store (T03) will persist the `FileRecord`s and use `sha256` for incremental re-index.
- `scan` in `cli.py` wires intake, discovery and the adapters together and prints the
  census.
