"""Part 3 of the repository layer: files that change together in git history.

For files a and b, `support` is the number of commits that changed both, and
`confidence` is support divided by the commits that changed a. The measure is
directional: a small helper that changes only alongside a big module gets a high
confidence towards the module, while the module, changed often on its own, gets a low
one back. So a pair gives two edges, each with its own confidence.

Only `git log` and `git rev-parse` run, read-only. `--no-renames` lets git list changed
paths from trees alone, so a blobless clone never downloads old file contents.
"""

from __future__ import annotations

import os
import subprocess
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from codeatlas.models import Edge, EdgeKind, FileRecord, Node, Resolution
from codeatlas.repo.paths import basename, module_id

LOCKFILES = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock",
    "Cargo.lock", "go.sum", "composer.lock",
})
VENDORED_FOLDERS = frozenset({"vendor", "dist", "build", "node_modules"})
GENERATED_SUFFIXES = (
    ".min.js", ".min.css", ".min.mjs", ".map",
    "_pb2.py", "_pb2_grpc.py", ".pb.go", ".g.dart", ".designer.cs", ".g.cs",
)

_COMMIT_MARK = "\x1e"  # ASCII record separator: cannot appear in a path git prints
_GIT_TIMEOUT = 120


@dataclass(slots=True)
class History:
    """Changed paths per commit, newest first, or the reason there are none."""

    commits: list[list[str]] = field(default_factory=list)
    status: str = "ok"
    shallow: bool = False


class CoChangeAnalyzer:
    """CO_CHANGES edges between module nodes, from the last `max_commits` commits."""

    name = "cochange"

    def __init__(
        self,
        max_commits: int = 2_000,
        min_support: int = 3,
        max_files_per_commit: int = 50,
        max_targets: int = 20,
        lockfiles: frozenset[str] = LOCKFILES,
        vendored_folders: frozenset[str] = VENDORED_FOLDERS,
        generated_suffixes: tuple[str, ...] = GENERATED_SUFFIXES,
    ) -> None:
        self.max_commits = max_commits
        self.min_support = min_support
        self.max_files_per_commit = max_files_per_commit
        self.max_targets = max_targets
        self.lockfiles = lockfiles
        self.vendored_folders = vendored_folders
        self.generated_suffixes = generated_suffixes
        self.report: dict[str, object] = {}

    def analyze(
        self, repo_root: Path, files: Sequence[FileRecord], snapshot_id: str
    ) -> tuple[list[Node], list[Edge]]:
        history = read_history(repo_root, self.max_commits)
        present = {f.path for f in files}
        changed, together, stats = self._count(history.commits, present)
        edges, dropped = self._edges(changed, together, snapshot_id)
        self.report = {
            "status": history.status,
            "shallow": history.shallow,
            "max_commits": self.max_commits,
            "commits_read": len(history.commits),
            "history_truncated": len(history.commits) >= self.max_commits,
            **stats,
            "edges": len(edges),
            "targets_over_limit": dropped,
        }
        return [], edges

    def _count(
        self, commits: list[list[str]], present: set[str]
    ) -> tuple[Counter[str], Counter[tuple[str, str]], dict[str, object]]:
        """Commits per file and per unordered pair, after every filter."""
        changed: Counter[str] = Counter()
        together: Counter[tuple[str, str]] = Counter()
        removed: dict[str, set[str]] = {
            "vendored": set(), "lockfile": set(), "generated": set(), "not_in_snapshot": set(),
        }
        large = 0
        for paths in commits:
            if len(paths) > self.max_files_per_commit:
                large += 1
                continue
            kept = []
            for path in paths:
                reason = self._filter_reason(path, present)
                if reason:
                    removed[reason].add(path)
                else:
                    kept.append(path)
            kept = sorted(set(kept))
            changed.update(kept)
            together.update(combinations(kept, 2))
        stats: dict[str, object] = {
            "commits_analysed": len(commits) - large,
            "commits_skipped_large": large,
            "files_removed": {reason: len(paths) for reason, paths in removed.items()},
        }
        return changed, together, stats

    def _filter_reason(self, path: str, present: set[str]) -> str | None:
        """Why a changed path is left out, or None to keep it. The first reason wins."""
        folders = path.split("/")[:-1]
        name = basename(path)
        if any(f in self.vendored_folders for f in folders):
            return "vendored"
        if name in self.lockfiles:
            return "lockfile"
        lowered = name.lower()
        if lowered.endswith(self.generated_suffixes) or ".generated." in lowered:
            return "generated"
        if path not in present:
            return "not_in_snapshot"
        return None

    def _edges(
        self, changed: Counter[str], together: Counter[tuple[str, str]], snapshot_id: str
    ) -> tuple[list[Edge], int]:
        """Both directions of every pair with enough support, the strongest few per file."""
        targets: dict[str, list[tuple[float, int, str]]] = defaultdict(list)
        for (a, b), support in together.items():
            if support < self.min_support:
                continue
            targets[a].append((support / changed[a], support, b))
            targets[b].append((support / changed[b], support, a))
        edges: list[Edge] = []
        dropped = 0
        for source in sorted(targets):
            ranked = sorted(targets[source], key=lambda t: (-t[0], -t[1], t[2]))
            dropped += max(0, len(ranked) - self.max_targets)
            for confidence, support, target in ranked[: self.max_targets]:
                edges.append(
                    Edge(module_id(snapshot_id, source), module_id(snapshot_id, target),
                         EdgeKind.CO_CHANGES, confidence, Resolution.HISTORY,
                         attrs={"support": support, "source_commits": changed[source]})
                )
        return edges, dropped


def read_history(repo_root: Path, max_commits: int) -> History:
    """Changed paths of the last `max_commits` non-merge commits reachable from HEAD.

    The folder must be the top of its own git repository: a plain folder that happens to
    sit inside another repository (a home folder under git, say) has no history of its
    own, and borrowing the outer one would invent co-changes.
    """
    top, why = _run_git(repo_root, "rev-parse", "--show-toplevel")
    if top is None:
        return History(status=why)
    try:
        same = os.path.samefile(top.strip(), repo_root)
    except OSError:
        same = False
    if not same:
        return History(status=f"not the top of a git repository (inside {top.strip()})")
    if _git(repo_root, "rev-parse", "--verify", "--quiet", "HEAD") is None:
        return History(status="no commits")
    shallow = (_git(repo_root, "rev-parse", "--is-shallow-repository") or "").strip() == "true"
    log, why = _run_git(
        repo_root, "log", "--no-merges", "--no-renames", "--name-only", "--no-color",
        f"--format={_COMMIT_MARK}%H", f"--max-count={max_commits}", "HEAD", "--",
    )
    if log is None:
        return History(status=f"git log failed: {why}", shallow=shallow)
    return History(commits=parse_log(log), shallow=shallow)


def parse_log(text: str) -> list[list[str]]:
    """`\\x1e<sha>\\n\\npath\\npath\\n...` per commit -> the paths of each commit."""
    commits = []
    for chunk in text.split(_COMMIT_MARK)[1:]:
        lines = chunk.splitlines()
        commits.append([line for line in lines[1:] if line])
    return commits


def _git(repo_root: Path, *args: str) -> str | None:
    """stdout of a read-only git command, or None if git is missing or the command fails."""
    return _run_git(repo_root, *args)[0]


def _run_git(repo_root: Path, *args: str) -> tuple[str | None, str]:
    """(stdout, "") on success, or (None, why it failed) so the summary can say why.

    "git not found" (common on a Windows machine without git on PATH) must not read as
    "not a git repository".

    `core.quotePath=off` prints non-ASCII paths as they are instead of octal escapes, so
    they match the snapshot's paths; `log.showSignature=false` keeps signature checks out
    of the path list; `core.fsmonitor=false` stops a repository's config from starting a
    program.
    """
    command = [
        "git", "-c", "core.quotePath=off", "-c", "log.showSignature=false",
        "-c", "core.fsmonitor=false", "-C", str(repo_root), *args,
    ]
    try:
        done = subprocess.run(command, capture_output=True, timeout=_GIT_TIMEOUT, check=False)
    except FileNotFoundError:
        return None, "git not found: install git or put it on PATH"
    except subprocess.TimeoutExpired:
        return None, f"git timed out after {_GIT_TIMEOUT} s"
    except OSError as exc:
        return None, f"git could not start: {exc}"
    if done.returncode != 0:
        stderr = done.stderr.decode("utf-8", "replace").strip()
        first = stderr.splitlines()[0] if stderr else f"exit status {done.returncode}"
        if "not a git repository" in first:
            return None, "not a git repository"
        return None, first
    return done.stdout.decode("utf-8", "surrogateescape"), ""
