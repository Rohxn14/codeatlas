# Intake and discovery

Modules: `src/codeatlas/indexer/intake.py`, `src/codeatlas/indexer/discover.py`,
`src/codeatlas/config.py`, and the `scan` command in `src/codeatlas/cli.py`.

## What

**Intake** turns what the user typed into a folder on disk and a commit SHA. A local
path is used as it is. A public repository URL (`https://github.com/owner/repo`, optionally
`@ref`) is cloned into `.codeatlas/repos/<owner>__<repo>/` and reused while the remote
still points at the same commit. Four hosts are accepted: github.com, gitlab.com,
bitbucket.org and codeberg.org (the tuple `HOSTS` in `intake.py`). A clone from a host
other than GitHub goes into `<host>__<owner>__<repo>/`. Any other address is refused
with a message that names the four hosts; so is a GitLab subgroup address
(`group/subgroup/repo`), because only `owner/repo` is read.

**Discovery** lists every file in that folder and returns a `FileRecord` for each one:
repo-relative forward-slash path, language, tier, SHA-256 and size. A file that cannot be
analysed (binary, minified, over the size limit) is still a record, at tier `TEXT`, and
`skip_reasons` says why; `scan` turns it into a module node with `attrs["skipped_reason"]`.
What discovery does not enter at all (a `node_modules`-style folder, a symlink, a git
submodule) is listed once in `skipped`, with its reason and, for a folder, how many files
it holds.

**Config** holds the limits: 200,000 files, 5 MB per parsed file and 3,600 seconds per
index by default (since Nov 25; 20,000, 1 MB and 300 before), plus `max_history_commits`
(2,000) for the repository layer. When the file or time limit is reached, indexing stops,
keeps what it has, and names the limit in `Snapshot.limits_hit`; a larger file only goes
unparsed (below).

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
- **`git ls-files` only at a repository's top level.** When the scanned folder is the
  top level of its repository (`git rev-parse --show-toplevel` is the folder itself),
  git already knows exactly which files belong to it and applies every `.gitignore`,
  global excludes and `.git/info/exclude` correctly. A folder *inside* some other
  repository is walked instead: an untracked project under a home folder that is itself
  a git repository would otherwise lose every file the outer repository *ignores*.
  Intake follows the same rule (`is_repo_top_level`): only a repository's top level gets
  a commit SHA; any other folder is named by a hash of its files' contents. Untracked
  files that are not ignored are included
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
   `git clone --quiet --filter=blob:none --single-branch --no-tags -c core.longpaths=true
   [--branch <ref>] -- <url> <tmp>`, then write the mark. On failure, delete the temporary
   folder and leave the target alone. `core.longpaths` is saved in the clone's own config:
   Git for Windows refuses paths over 260 characters without it (microsoft/TypeScript
   has 23 such paths once cloned under `.codeatlas/`), and later commands in the clone
   (`checkout`, `diff`) need it too. `--quiet` keeps progress lines out of the error.
5. Swap: rename the old clone aside, rename the new one into place, then delete the old
   one. Two renames, because Windows cannot rename onto an existing folder. Each rename
   is retried for about five seconds on a permission error: Windows refuses to rename a
   folder while another program (antivirus, search indexer, an editor) has a file in it
   open, and it does that to a fresh clone for a moment. In the Nov 15 suite run on
   Windows, 9 of 47 repositories failed this way, and each succeeded when re-run.
6. A local path must be an existing folder; its SHA is `git rev-parse HEAD`, or `None`
   outside git (then `scan` uses a hash of all file hashes instead).
7. The snapshot's `source` is the URL as given, or, for a local folder, its resolved
   absolute path (`C:/work/app`, never `.`). Queries run from other folders find the
   checkout through it: the MCP server starts wherever Claude Code is opened, and a
   relative `.` would mean that folder.

Discovery (`discover`):

1. List candidates: at a repository's top level, `git ls-files`, then drop paths under an excluded folder
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
- The deadline is read from `time.perf_counter` (since Nov 26). On Windows `time.monotonic`
  moves in steps of 15.6 ms, so a limit shorter than one step could not end until the clock
  happened to tick; a test with a one-microsecond limit failed in 9 of 10 runs that way.
- A changed remote SHA means a full new clone, not a fetch: cheap when blobless, slow for
  very large repositories.
- Reuse works for branches and tags; a bare commit SHA as `@ref` is not supported, because
  `ls-remote` cannot see it.
- Clones made before the CodeAtlas mark existed are refused rather than replaced; delete
  them by hand once. A crash between the two renames can leave a `.<name>.old-*` or
  `.<name>.*.tmp` folder beside the clone; delete those by hand too.
- Inside git, untracked files that are not ignored are scanned, but the snapshot still
  carries `HEAD`'s SHA, so a dirty work tree is indexed under the commit's id.
- A folder walked because it sits inside another repository applies only the
  `.gitignore` files at or below it, not the outer repository's, so files the outer
  repository ignores (for example `__pycache__`) appear in the census.
- In git mode a `.gitignore`d `node_modules` is never seen, so it is not listed; the walk
  lists excluded folders even when ignored. The two modes differ there.

## Nothing stops early, and nothing secret is read (Nov 25)

**What the owner saw.** Every repository showed "Indexing stopped early at a limit
(max_file_bytes)". Nothing had stopped: PitwallOS had six images over 1 MB, logfire a lock file
and a screenshot, `cli` two git pack files. A large file is now looked at for binary content
*before* its size, so an image is "binary", not a limit. Only `max_files` and `max_seconds` stop
a run, and the message says so only for those two.

**Limits.** They are a guard, not a budget: 200,000 files, 3,600 s, and 5 MB for one file to be
parsed into symbols (from 20,000, 300 s and 1 MB). A longer text file keeps its first megabyte
searchable. The tracked `codeatlas.toml` carries the same numbers; it overrides the defaults in
the folder it sits in, so the old ones there would have kept the old limits.

**The text of every text file** (D-59). A `.gitignore`, a workflow or a requirements file has no
symbols, so the map knew its name and nothing else: searching `__pycache__` found nothing, and
"What does the gitignore exclude?" could not be answered. `split_parts` (`generic/sections.py`)
cuts such a file into parts of at most 60 lines or 4,000 characters, each a SECTION node, as a
README's headings already were. At most 50 parts per file (a lock file is not worth more), and
the module says at which line they stop. Vectors are built only for files of three parts or
fewer; text search covers the rest.

**Files that may hold secrets** (D-60). Reading every file's text means a `.env` in a folder that
is not a git repository would be stored and could reach a language model. `is_secret_path` knows
such files by name (`.env`, `.env.*` but not `.env.example`, `.pem`, `.key`, `id_rsa`,
`credentials.json` and others). They stay on the map by name, their bytes are never read (the
stored hash is of the name and size), and the agent's tools and the file page refuse them too,
which also covers snapshots indexed before this.
