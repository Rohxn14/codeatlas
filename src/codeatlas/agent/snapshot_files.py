"""A file as it was when its snapshot was indexed, even after the checkout moved on.

The map holds line numbers, the checkout holds the lines. When the owner commits after
indexing, the two no longer match: an answer about the old snapshot would read new lines at
old numbers. The stored hash says which bytes are the right ones.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from codeatlas.indexer.discover import is_secret_path


def snapshot_bytes(root: Path | None, commit_sha: str, path: str, sha256: str) -> bytes | None:
    """The indexed bytes of one file: from the checkout, else from the commit; else None.

    None also for a path outside the checkout and for a file that may hold secrets.
    """
    if root is None or is_secret_path(path):
        return None
    base = root.resolve()
    target = (base / path).resolve()
    if not target.is_relative_to(base):
        return None
    try:
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() == sha256:
            return data
    except OSError:
        pass  # moved or deleted since: the commit may still have it
    return _from_commit(base, commit_sha, path, sha256)


def _from_commit(root: Path, commit_sha: str, path: str, sha256: str) -> bytes | None:
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "show", f"{commit_sha}:{path}"],
            capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    # Git stores LF; a Windows checkout that was indexed had CRLF, and so has its hash.
    for data in (done.stdout, done.stdout.replace(b"\n", b"\r\n")):
        if hashlib.sha256(data).hexdigest() == sha256:
            return data
    return None
