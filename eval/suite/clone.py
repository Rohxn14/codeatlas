"""Fetch a pinned repository through the existing intake, then pin it to its commit.

`codeatlas.indexer.intake` makes a blobless single-branch clone of the default branch
(full history, file contents only for what is checked out). The suite wants a specific
older commit, so the clone is followed by `git checkout --detach <sha>`; blobs for that
commit are fetched on demand. Nothing from the repository is built or run.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from codeatlas.indexer.intake import IntakeError, clone_or_reuse, head_sha
from eval.suite.repos import RepoSpec

DEFAULT_CLONES = Path(".codeatlas") / "eval" / "repos"
_CHECKOUT_TIMEOUT = 900


def clone_pinned(spec: RepoSpec, clones_dir: Path = DEFAULT_CLONES) -> Path:
    """A clone of `spec` at `spec.sha`; raises `IntakeError` with the reason on failure."""
    dest = clones_dir / spec.name
    if head_sha(dest) == spec.sha:
        return dest.resolve()
    clone_or_reuse(spec.url, dest)
    if head_sha(dest) != spec.sha:
        _checkout(dest, spec.sha)
    return dest.resolve()


def _checkout(root: Path, sha: str) -> None:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
    command = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(root),
        "checkout",
        "-q",
        "--detach",
        sha,
    ]
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, timeout=_CHECKOUT_TIMEOUT, env=env, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise IntakeError(f"git checkout {sha} failed: {exc}") from exc
    if done.returncode != 0:
        raise IntakeError(f"git checkout {sha} failed: {done.stderr.strip()}")
