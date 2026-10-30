"""Intake: turn what the user typed (a local path or a public GitHub URL) into a folder on disk.

A URL is fetched with one blobless, single-branch `git clone`: the full commit history
comes along (the repository layer needs it for co-change), but file contents only for
the checked-out commit. Nothing is fetched file by file through the GitHub REST API,
and nothing from the cloned repository is ever run.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from codeatlas.config import Config

_GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
# Branch and tag names: no leading dash (it would read as a git option), no "..".
_REF = re.compile(r"^(?!-)(?!.*\.\.)[A-Za-z0-9_./-]+$")
_CLONE_TIMEOUT_SECONDS = 600
_GIT_TIMEOUT_SECONDS = 60
# Written inside `.git/` (so discovery never lists it) to mark a clone as CodeAtlas's own.
_MARKER = Path(".git") / "codeatlas-clone"


class IntakeError(Exception):
    """The source cannot be used: a bad URL, a missing folder or a failed git command."""


@dataclass(frozen=True, slots=True)
class GitHubSource:
    """A parsed `https://github.com/owner/repo[@ref]`."""

    owner: str
    repo: str
    ref: str | None = None

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}.git"

    @property
    def dirname(self) -> str:
        """Folder name under `.codeatlas/repos/`."""
        return f"{self.owner}__{self.repo}"


@dataclass(frozen=True, slots=True)
class IntakeResult:
    """Where the code is and which commit it is; `commit_sha` is None outside git."""

    root: Path
    repo: str
    source: str
    commit_sha: str | None
    reused_clone: bool = False


def looks_like_url(text: str) -> bool:
    """True for anything with a URL scheme, so a bad URL is rejected instead of read as a path."""
    return "://" in text


def parse_github_url(text: str) -> GitHubSource:
    """Parse `https://github.com/owner/repo`, optionally ending in `.git`, `/` or `@ref`."""
    parts = urlsplit(text.strip())
    if parts.scheme != "https":
        raise IntakeError(f"only https URLs are accepted: {text!r}")
    host = (parts.hostname or "").lower()
    if host not in _GITHUB_HOSTS or parts.username or parts.password or parts.port:
        raise IntakeError(f"only public github.com URLs are accepted: {text!r}")
    if parts.query or parts.fragment:
        raise IntakeError(f"URL must not have a query or fragment: {text!r}")
    owner, _, rest = parts.path.strip("/").partition("/")
    repo, at, ref = rest.partition("@")
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    if not _NAME.match(owner) or not _NAME.match(repo):
        raise IntakeError(f"expected https://github.com/<owner>/<repo>[@ref]: {text!r}")
    if at and not _REF.match(ref):
        raise IntakeError(f"invalid ref {ref!r} in {text!r}")
    return GitHubSource(owner=owner, repo=repo, ref=ref if at else None)


def open_source(source: str, config: Config) -> IntakeResult:
    """Resolve a local path or a GitHub URL to an `IntakeResult` ready for discovery."""
    if looks_like_url(source):
        github = parse_github_url(source)
        dest = config.repos_dir / github.dirname
        sha, reused = clone_or_reuse(github.clone_url, dest, github.ref)
        return IntakeResult(dest.resolve(), github.repo, source, sha, reused)
    root = Path(source).expanduser().resolve()
    if not root.is_dir():
        raise IntakeError(f"not a folder: {source}")
    return IntakeResult(root, root.name, source, head_sha(root))


def clone_or_reuse(remote: str, dest: Path, ref: str | None = None) -> tuple[str, bool]:
    """Make `dest` a blobless clone of `remote` at `ref`; return (commit SHA, reused).

    An existing clone is kept when its HEAD already matches the remote's SHA for `ref`.
    Otherwise a fresh clone is made in a temporary folder beside `dest` and swapped in
    only once it has succeeded, so a failed clone never costs the previous one. Only
    folders that CodeAtlas created (marked inside `.git/`) are ever replaced or deleted.
    """
    remote_sha = _remote_sha(remote, ref)
    if _is_codeatlas_clone(dest):
        local_sha = head_sha(dest)
        if local_sha is not None and local_sha == remote_sha:
            return local_sha, True
    elif dest.is_symlink() or (dest.exists() and not _is_empty_dir(dest)):
        raise IntakeError(
            f"refusing to replace {dest}: it was not created by CodeAtlas; "
            "move or delete it yourself"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    fresh = Path(tempfile.mkdtemp(prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent))
    try:
        sha = _clone_into(remote, fresh, ref)
        _swap_in(fresh, dest)
    except BaseException:
        _remove_tree(fresh)  # made by mkdtemp above, so it is ours
        raise
    return sha, False


def _clone_into(remote: str, folder: Path, ref: str | None) -> str:
    """Clone into an empty folder, mark it as CodeAtlas's, and return its HEAD."""
    args = ["clone", "--filter=blob:none", "--single-branch", "--no-tags"]
    if ref:
        args += ["--branch", ref]
    _git([*args, "--", remote, str(folder)], timeout=_CLONE_TIMEOUT_SECONDS)
    (folder / _MARKER).write_text(remote + "\n", encoding="utf-8")
    sha = head_sha(folder)
    if sha is None:
        raise IntakeError(f"clone of {remote} has no HEAD commit")
    return sha


def _swap_in(fresh: Path, dest: Path) -> None:
    """Replace `dest` with `fresh`; the old clone is deleted only after the swap.

    Two renames rather than one, because Windows cannot rename onto an existing folder.
    """
    if not dest.exists():
        fresh.rename(dest)
        return
    if not _is_codeatlas_clone(dest):  # an empty folder: nothing to keep
        dest.rmdir()
        fresh.rename(dest)
        return
    old = dest.with_name(f".{dest.name}.old-{uuid.uuid4().hex[:8]}")
    dest.rename(old)
    try:
        fresh.rename(dest)
    except OSError:
        old.rename(dest)
        raise
    _remove_tree(old)  # checked by _is_codeatlas_clone above


def _is_empty_dir(path: Path) -> bool:
    return path.is_dir() and not any(path.iterdir())


def _is_codeatlas_clone(path: Path) -> bool:
    return not path.is_symlink() and (path / _MARKER).is_file()


def head_sha(root: Path) -> str | None:
    """The commit checked out at `root`, or None when it is not inside a git work tree."""
    try:
        return _git(["-C", str(root), "rev-parse", "--verify", "HEAD"]).strip() or None
    except IntakeError:
        return None


def _remote_sha(remote: str, ref: str | None) -> str:
    """Ask the remote which commit `ref` (or its default branch) points at, without cloning."""
    patterns = [ref, f"{ref}^{{}}"] if ref else ["HEAD"]  # "^{}" asks for peeled tags too
    out = _git(["ls-remote", "--", remote, *patterns])
    found: dict[str, str] = {}
    for line in out.splitlines():
        sha, _, name = line.partition("\t")
        found[name.strip()] = sha.strip()
    if not ref:
        if "HEAD" in found:
            return found["HEAD"]
    else:
        # A peeled annotated tag names the commit itself; prefer it over the tag object.
        for name in (f"refs/tags/{ref}^{{}}", f"refs/heads/{ref}", f"refs/tags/{ref}"):
            if name in found:
                return found[name]
    raise IntakeError(f"ref {ref or 'HEAD'!r} not found on {remote}")


def _git(args: list[str], timeout: float = _GIT_TIMEOUT_SECONDS) -> str:
    """Run git without prompts, LFS downloads or fsmonitor hooks, and return stdout."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
    command = ["git", "-c", "core.fsmonitor=false", *args]
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, env=env, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise IntakeError(f"git {args[0]} failed: {exc}") from exc
    if done.returncode != 0:
        raise IntakeError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def _remove_tree(path: Path) -> None:
    """Delete a folder, including git's read-only pack files on Windows.

    Callers pass only a temporary folder this module just made, or a folder that
    `_is_codeatlas_clone` has confirmed.
    """

    def make_writable_and_retry(func, target, _exc):  # type: ignore[no-untyped-def]
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if not path.exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=make_writable_and_retry)
    else:
        shutil.rmtree(path, onerror=make_writable_and_retry)
