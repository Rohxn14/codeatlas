# Intake and discovery

Modules: `src/codeatlas/indexer/intake.py`, `src/codeatlas/indexer/discover.py`, `src/codeatlas/config.py`

## What

**Intake** turns what the user typed into a folder on disk and a commit SHA. A local path is used as it is. A public GitHub URL (`https://github.com/owner/repo`, optionally `@ref`) is cloned once into `.codeatlas/repos/<owner>__<repo>/` and reused while the remote still points at the same commit.

**Discovery** lists every file in that folder that is worth indexing, and for each one records its repo-relative path, language, tier, SHA-256 hash and size (`FileRecord`). Whatever it leaves out (a `node_modules` folder, a binary, a 3 MB generated file) is recorded with a reason, so nothing disappears silently.

**Config** reads limits from `codeatlas.toml`: at most 20,000 files, 1 MB per file and 300 seconds per index, plus `max_history_commits` for the repository layer. Reaching a limit stops the work, keeps what was done and names the limit in `Snapshot.limits_hit`.

## Why

- **One blobless `git clone`, not the GitHub API.** The REST API allows 60 unauthenticated requests an hour, so fetching file by file fails on any real repository. `--filter=blob:none` downloads every commit and tree (the co-change analysis in T15 needs the history) but file contents only for the commit we check out. A full clone would download every old version of every file; a shallow clone (`--depth 1`) would lose the history.
- **Reuse by SHA.** `git ls-remote` asks the server which commit a ref points to without downloading anything. If the clone already shows that commit, intake does nothing. Otherwise it fetches and checks out the new commit in place rather than deleting and re-cloning, which keeps the history already downloaded.
- **Strict URL parsing.** Only `https://github.com/<owner>/<repo>` is accepted. Other hosts, look-alike hosts (`github.com.evil.com`), refs starting with `-` (which git could read as an option) and `..` are rejected before git runs. `clone` and `ls-remote` also put `--` before the URL for the same reason.
- **Nothing from the clone runs.** Clone uses `--no-recurse-submodules`, `GIT_LFS_SKIP_SMUDGE=1` and `GIT_TERMINAL_PROMPT=0` (a private repository fails instead of hanging on a password prompt). git does not run hooks shipped inside a repository.
- **`git ls-files` inside git, a walk outside.** Inside a work tree git already knows exactly which files belong to the repository, including every nested `.gitignore` and `.git/info/exclude` rule. `--others --exclude-standard` adds new files you have not committed yet but that are not ignored. Outside git, a walk applies each `.gitignore` it meets, using `pathspec` (the same matching rules as git). Writing our own glob matcher was rejected: gitignore semantics (negation, anchoring, directory-only patterns) are subtle.
- **Always-skipped folders are skipped even when committed.** Some repositories commit `node_modules` or `dist`; indexing them would bury the real code. Each such folder is recorded once (`node_modules: excluded directory`), not once per file inside it.
- **Named text languages.** The contract allows `language` to be a grammar name or `"text"`. A Kotlin file has no grammar yet, but calling it `kotlin` (tier TEXT) lets the census say "40 Kotlin files, text tier" instead of hiding them in a "text" pile. Unknown extensions become `"text"`.
- **Config from where you run, not from the repository.** A repository could ship its own `codeatlas.toml` with huge limits; reading config from the current directory means only the person running CodeAtlas sets them.
- **Rejected: a hash-free discovery.** Hashing reads every file, which costs time, but the hash is what later lets the store re-index only changed files, so discovery pays for it once.

## How

`intake(source, repos_dir)`:

1. If `source` contains `://`, parse it with `parse_github_url`, which returns `GitHubRef(owner, repo, ref)` or raises `ValueError`.
2. `clone_or_reuse(clone_url, dest, ref)`:
   - if `dest/.git` exists, compare `git rev-parse HEAD` with `git ls-remote <url> <ref or HEAD>`; equal means reuse. For an annotated tag the `^{}` line (the commit the tag points to) wins.
   - if they differ, `git fetch --filter=blob:none origin <ref>` and `git checkout --force --detach FETCH_HEAD`.
   - if there is no clone yet, `git clone --filter=blob:none --single-branch --no-recurse-submodules [--branch ref] -- <url> <dest>`. A folder that exists but is not a clone is an error, not something to delete.
3. Otherwise resolve the local path; its SHA is `HEAD` when it sits inside git, else `None` (the CLI then uses a hash of every file's path and hash, so the snapshot id is still stable).

`discover(root, limits, tier_for, deadline)`:

1. List candidate paths: `git ls-files -z --cached --others --exclude-standard`, or a walk that prunes ignored and always-skipped folders.
2. Drop paths under `node_modules`, `.venv`, `venv`, `dist`, `build`, `.git`, recording each folder once.
3. In sorted path order, for each file: skip symlinks, minified files (`*.min.js`), files over `max_file_bytes` and binaries (a NUL byte in the first 8 KB), each with its reason. Otherwise detect the language from the extension or file name, ask `tier_for(language)` (by default the registry, so the tier always matches the adapter that will parse it) and hash the bytes.
4. Stop when `max_files` records exist or the deadline passes, and name the limit.

**Worked example.** A folder holds:

```
.gitignore          "*.log"
app.py
web/client.ts
debug.log
node_modules/x/index.js
logo.png            (starts with \x89PNG\r\n\x1a\n\x00)
```

Outside git, the walk reads `.gitignore`, so `debug.log` is ignored as git would ignore it; `node_modules` is pruned and recorded once. The result is:

| path | language | tier |
| --- | --- | --- |
| `.gitignore` | text | text |
| `app.py` | python | structural |
| `web/client.ts` | typescript | structural |

with `skipped = [node_modules: excluded directory, logo.png: binary]`. With `max_files = 2`, discovery would stop after `app.py` and report `limits_hit = ("max_files",)`.

## Where

- **Inputs:** a path or URL from the CLI (`codeatlas scan`), and `Limits` from `config.py`.
- **Outputs:** `Checkout` (root, repo name, SHA, source) and `Discovery` (`FileRecord`s, `SkippedFile`s, limits hit). The CLI builds the `Snapshot` (`make_snapshot_id(repo, sha)`) from them.
- **Contract types used:** `FileRecord`, `Tier`, `Snapshot`, `make_snapshot_id`.
- **Used next by:** the registry and adapters (one `ParseResult` per `FileRecord`), the repository layer (T15 reads `FileRecord`s and the clone's history up to `max_history_commits`), and the store (T03 keys incremental re-indexing on `sha256`).
- `run_git` in `intake.py` is the one place CodeAtlas calls git; discovery reuses it.
