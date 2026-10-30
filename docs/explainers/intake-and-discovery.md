# Intake and discovery

Modules: `src/codeatlas/indexer/intake.py`, `src/codeatlas/indexer/discover.py`,
`src/codeatlas/config.py`, and the `scan` command in `src/codeatlas/cli.py`.

## What

**Intake** turns what the user typed into a folder on disk and a commit SHA. A local
path is used as it is. A public GitHub URL (`https://github.com/owner/repo`, optionally
`@ref`) is cloned into `.codeatlas/repos/<owner>__<repo>/` and reused while the remote
still points at the same commit.

**Discovery** lists every file in that folder and returns a `FileRecord` for each one:
repo-relative forward-slash path, language, tier, SHA-256 and size. A file that cannot be
analysed (binary, minified, over the size limit) is still a record, at tier `TEXT`, and
`skip_reasons` says why; `scan` turns it into a module node with `attrs["skipped_reason"]`.
What discovery does not enter at all (a `node_modules`-style folder, a symlink, a git
submodule) is listed once in `skipped`, with its reason and, for a folder, how many files
it holds.

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
  reused. Rejected: `git fetch` into the existing clone, which is faster for big
  repositories but has awkward corner cases with single-branch blobless clones and
  changing refs.
- **Clone beside, then swap.** A new clone goes into a temporary folder next to the old
  one and replaces it only after it succeeded, so a failed or interrupted clone never
  costs the clone you had. Rejected: deleting first and cloning in place, which is
  simpler but loses the old clone whenever the network fails.
- **Delete only what CodeAtlas made.** Each clone is marked with `.git/codeatlas-clone`.
  Intake replaces or deletes a folder only if it carries that mark (or is the temporary
  folder it just created); any other non-empty folder at the target path is refused with
  an error. The mark lives inside `.git/` so `git ls-files` never reports it.
- **`git ls-files` when possible.** Inside a git work tree, git already knows exactly
  which files belong to the repository and applies every `.gitignore`, global excludes
  and `.git/info/exclude` correctly. Untracked files that are not ignored are included
  (`--others --exclude-standard`), so a local work in progress is scanned too. Outside git
  the code walks the folder and applies `.gitignore` files with `pathspec`, the same
  matching rules git uses.
- **No silent gaps.** Every file is a record, parsed or not, and every folder left out is
  named once with its file count. One entry per folder rather than one per file keeps a
  `node_modules` with 50,000 files from flooding the census.
- **The time limit covers indexing, not cloning.** The 300-second clock starts after
  intake, so a slow network does not eat the parse budget. The clone has its own timeout.
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
3. If the target folder carries the CodeAtlas mark and its `HEAD` equals that SHA, reuse
   it. If the target exists, is not empty and has no mark, stop with an error.
4. Otherwise clone into a new temporary folder beside the target:
   `git clone --filter=blob:none --single-branch --no-tags [--branch <ref>] -- <url> <tmp>`,
   then write the mark. On failure, delete the temporary folder and leave the target alone.
5. Swap: rename the old clone aside, rename the new one into place, then delete the old
   one. Two renames, because Windows cannot rename onto an existing folder.
6. A local path must be an existing folder; its SHA is `git rev-parse HEAD`, or `None`
   outside git (then `scan` uses a hash of all file hashes instead).

Discovery (`discover`):

1. List candidates: `git ls-files`, then drop paths under an excluded folder
   (`node_modules`, `.venv`, `venv`, `dist`, `build`, `.git`, `.codeatlas`), counting
   them per folder. Outside git, walk instead: an excluded folder is not entered but its
   files are counted; a `.gitignore`d folder is not entered; a symlinked folder is
   recorded as `symlink`.
2. For each candidate in sorted order, stop with `max_seconds` if the deadline has passed,
   or `max_files` if that many records already exist.
3. Record a file symlink or a submodule in `skipped`. Otherwise make a record; a
   `*.min.js` file, a file over `max_file_bytes` (which also adds `max_file_bytes` to the
   limits hit) or a NUL byte in the first 8 KB (binary) makes it `TEXT` with a reason.
4. Otherwise pick the language from the file name or extension and ask the registry for
   the tier. An unknown extension is language `text`; `scan` records
   "unknown file type" as its reason.

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

The walk does not enter `logs/` (ignored) or `node_modules/` (excluded). Discovery returns:

| path | language | tier | skip reason |
| --- | --- | --- | --- |
| `.gitignore` | text | text | |
| `README.md` | markdown | text | |
| `app.py` | python | structural | |
| `web/App.tsx` | tsx | structural | |
| `web/vendor.min.js` | javascript | text | minified |

and `skipped = [("node_modules", "excluded directory", 1 file)]`, `limits_hit = ()`. With
`max_files = 2` it would return the first two records and `limits_hit = ("max_files",)`.

## Where

- Contract types: `FileRecord`, `Tier` and `Snapshot` (`limits_hit`) from
  `codeatlas.models`; `make_snapshot_id` builds the snapshot id in `scan`.
- Discovery takes `tier_for` from `indexer/registry.py`, so a file's tier is what will
  really happen to it: a language whose grammar fails to load is reported as text.
- The repository layer (T15) reads `max_history_commits` and the clone's history; the
  store (T03) will persist the `FileRecord`s and use `sha256` for incremental re-index.
- `scan` in `cli.py` wires intake, discovery and the adapters together, gives each
  skipped file its TEXT node, and prints the census with one row per (language, tier).

## Known limitations

- The clone has a fixed 600-second timeout of its own; it does not count against
  `max_seconds`, which starts after intake.
- A changed remote SHA means a full new clone, not a fetch: cheap when blobless, slow for
  very large repositories.
- Reuse works for branches and tags; a bare commit SHA as `@ref` is not supported, because
  `ls-remote` cannot see it.
- Clones made before the CodeAtlas mark existed are refused rather than replaced; delete
  them by hand once. A crash between the two renames can leave a `.<name>.old-*` or
  `.<name>.*.tmp` folder beside the clone; delete those by hand too.
- Inside git, untracked files that are not ignored are scanned, but the snapshot still
  carries `HEAD`'s SHA, so a dirty work tree is indexed under the commit's id.
- In git mode a `.gitignore`d `node_modules` is never seen, so it is not listed; the walk
  lists excluded folders even when ignored. The two modes differ there.
