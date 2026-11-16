"""Where a change comes from, for the impact page: git, a pasted diff, a file or a symbol.

The git commands here only read (`log`, `show`, `diff`, `rev-parse`). No diff driver,
text filter or file-watching hook of the repository is run, and git may not fetch
missing file contents from the network: a page view must never reach out.

**Line numbers.** The impact engine maps changed lines to symbols using the snapshot's
line numbers, so a change is `exact` only when its line numbers are the snapshot's:

- the snapshot's own commit: the new side of its diff is the snapshot;
- uncommitted changes: the diff is asked for in reverse (`git diff -R HEAD`), which
  makes the indexed commit the new side;
- an older commit: its line numbers have moved since, so each changed file counts
  whole, and the page says so.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from codeatlas.impact.diff import parse_diff
from codeatlas.impact.models import Change
from codeatlas.models import Snapshot

MAX_COMMITS = 15
MAX_DIFF_BYTES = 2_000_000
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_TIMEOUT_SECONDS = 30
_SEP = "\x1f"
# What every diff here is asked for with: plain text, no program of the repository run.
# `-U0` leaves out the three unchanged lines git prints round each edit. The diff reader
# takes a hunk's whole span as changed, so with them a one-line edit would also mark a
# neighbouring function that starts within three lines of it.
_PLAIN = ("--no-color", "--no-ext-diff", "--no-textconv", "--relative", "-U0")
_WHOLE_FILES = ("Line numbers in this change may not match the indexed commit, so each "
                "changed file counts whole. The result is wider than the change really is.")


class ChangeError(ValueError):
    """The change cannot be read; the message is shown on the page."""


@dataclass(frozen=True, slots=True)
class Commit:
    sha: str
    date: str
    subject: str


@dataclass(frozen=True, slots=True)
class ChangeSet:
    """A change ready for the engine, with what to call it and how exact it is."""

    title: str
    changes: tuple[Change, ...]
    exact: bool
    note: str = ""


def git(root: Path, *args: str) -> str | None:
    """Output of one read-only git command in the checkout, or None when it fails."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0",
           "GIT_NO_LAZY_FETCH": "1"}
    command = ["git", "-C", str(root), "-c", "core.fsmonitor=false", *args]
    try:
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=_TIMEOUT_SECONDS, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def at_snapshot(root: Path | None, snapshot: Snapshot) -> bool:
    """True when the checkout's HEAD is still the indexed commit."""
    if root is None:
        return False
    head = git(root, "rev-parse", "--verify", "HEAD")
    return head is not None and head.strip() == snapshot.commit_sha


def recent_commits(root: Path | None, snapshot: Snapshot, limit: int = MAX_COMMITS) -> list[Commit]:
    """The indexed commit and the ones before it, newest first; empty outside git."""
    if root is None or not _SHA.match(snapshot.commit_sha):
        return []
    out = git(root, "log", f"-n{limit}", f"--format=%H{_SEP}%cs{_SEP}%s",
              snapshot.commit_sha, "--", ".")
    return [Commit(*line.split(_SEP, 2)) for line in (out or "").splitlines()
            if line.count(_SEP) >= 2]


def commit_changes(root: Path | None, snapshot: Snapshot, sha: str) -> ChangeSet:
    """What one commit changed. `sha` comes from an address, so it must look like one."""
    if root is None:
        raise ChangeError("The indexed checkout is no longer on disk, so git cannot be read.")
    if not _SHA.match(sha):
        raise ChangeError(f"{sha!r} is not a commit id.")
    head = git(root, "show", "-s", f"--format=%H{_SEP}%cs{_SEP}%s", f"{sha}^{{commit}}", "--")
    if head is None or head.count(_SEP) < 2:
        raise ChangeError(f"There is no commit {sha} in the checkout.")
    commit = Commit(*head.strip().split(_SEP, 2))
    title = f"Commit {commit.sha[:7]}: {commit.subject}"
    if commit.sha == snapshot.commit_sha:
        patch = git(root, "show", "--format=", "--diff-merges=first-parent", *_PLAIN,
                    commit.sha, "--")
        if patch is not None:
            return ChangeSet(title, tuple(parse_diff(patch)), exact=True)
    names = git(root, "show", "--format=", "--name-only", "-z", "--diff-merges=first-parent",
                "--relative", commit.sha, "--")
    if names is None:
        raise ChangeError(f"git could not list the files of commit {sha}.")
    paths = [name for name in names.split("\0") if name.strip()]
    return ChangeSet(title, tuple(Change(path) for path in paths), exact=False,
                     note=_WHOLE_FILES)


def worktree_changes(root: Path | None, snapshot: Snapshot) -> ChangeSet:
    """Edits in the checkout that are not committed yet."""
    if root is None or not at_snapshot(root, snapshot):
        raise ChangeError("The checkout is not at the indexed commit, so its uncommitted "
                          "changes cannot be placed on this map. Index it again first.")
    # Reversed, so the indexed commit is the "new" side and line numbers are the snapshot's.
    patch = git(root, "diff", "-R", *_PLAIN, "HEAD", "--")
    if patch is None:
        raise ChangeError("git could not read the uncommitted changes.")
    return ChangeSet("Uncommitted changes in the checkout", tuple(parse_diff(patch)), exact=True)


def pasted_changes(text: str) -> ChangeSet:
    """A diff someone pasted. Its new side is taken to be the indexed commit."""
    changes = parse_diff(text)
    if not changes:
        raise ChangeError("No file headers were found in that text. Paste the output of "
                          "`git diff` or `git show`.")
    note = ("Line numbers are read from the new side of the diff, so they are right when "
            "the diff ends at the indexed commit. The unchanged lines a diff prints round "
            "each edit count as changed too, so a symbol next to an edit may be included.")
    return ChangeSet(f"A pasted diff of {len({c.path for c in changes})} files",
                     tuple(changes), exact=False, note=note)
