"""Read-only git helpers for the benchmark: the file list at a commit, and recent commits."""

from __future__ import annotations

import subprocess
from pathlib import Path

from codeatlas.repo.cochange import CoChangeAnalyzer, parse_log

_MARK = "\x1e"
_TIMEOUT = 300


def git_out(repo: Path, *args: str) -> str:
    """stdout of a read-only git command; raises `RuntimeError` with git's message on failure."""
    command = [
        "git",
        "-c",
        "core.quotePath=off",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(repo),
        *args,
    ]
    done = subprocess.run(command, capture_output=True, timeout=_TIMEOUT, check=False)
    if done.returncode != 0:
        raise RuntimeError(
            done.stderr.decode("utf-8", "replace").strip() or f"git {args[0]} failed"
        )
    return done.stdout.decode("utf-8", "surrogateescape")


def files_at(repo: Path, rev: str) -> set[str]:
    """Every file path in the tree of `rev` (no file contents are needed)."""
    return {p for p in git_out(repo, "ls-tree", "-r", "--name-only", rev).split("\n") if p}


def recent_commits(
    repo: Path, wanted: int, lowest: int = 2, highest: int = 20
) -> list[tuple[str, list[str]]]:
    """Newest-first (sha, kept files) of non-merge commits that qualify as held-out queries.

    A commit qualifies when, after the same filters the co-change analyzer uses (vendored
    folders, lockfiles, generated files, files gone from the commit's tree), it changed
    between `lowest` and `highest` files. Scans up to ten times `wanted` commits.
    """
    log = git_out(
        repo,
        "log",
        "--no-merges",
        "--no-renames",
        "--name-only",
        "--no-color",
        f"--format={_MARK}%H",
        f"--max-count={wanted * 10}",
        "HEAD",
        "--",
    )
    shas = [chunk.split("\n", 1)[0] for chunk in log.split(_MARK)[1:]]
    analyzer = CoChangeAnalyzer()
    found: list[tuple[str, list[str]]] = []
    for sha, paths in zip(shas, parse_log(log), strict=True):
        if len(paths) < lowest:
            continue
        present = files_at(repo, sha)
        kept = sorted({p for p in paths if analyzer._filter_reason(p, present) is None})
        if lowest <= len(kept) <= highest:
            found.append((sha, kept))
            if len(found) >= wanted:
                break
    return found
