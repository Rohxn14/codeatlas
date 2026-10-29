"""Intake: turn a local path or a public GitHub URL into a folder on disk and a commit SHA.

A URL is fetched with one blobless `git clone`: full commit history (the repository
layer's co-change analysis needs it) but file contents only for the checked-out commit.
Never the GitHub REST API file by file, and nothing from the clone is ever run.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")


@dataclass(frozen=True, slots=True)
class GitHubRef:
    """A parsed `https://github.com/owner/repo[@ref]`."""

    owner: str
    repo: str
    ref: str | None = None

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}.git"

    @property
    def folder_name(self) -> str:
        return f"{self.owner}__{self.repo}"


@dataclass(frozen=True, slots=True)
class Checkout:
    """A repository ready to discover: where it is and which commit it shows."""

    root: Path
    repo: str
    commit_sha: str | None
    source: str
    reused: bool = False


def is_url(source: str) -> bool:
    """True when `source` looks like a URL rather than a local path."""
    return "://" in source


def parse_github_url(url: str) -> GitHubRef:
    """Parse `https://github.com/owner/repo` with optional `.git`, trailing slash and `@ref`.

    Raises ValueError for any other host or shape, so nothing but github.com is ever cloned.
    """
    match = re.fullmatch(r"https://([^/]+)/(.+)", url.strip())
    if match is None:
        raise ValueError(f"not an https URL: {url!r}")
    host, rest = match.groups()
    if host.lower() not in {"github.com", "www.github.com"}:
        raise ValueError(f"only github.com URLs are supported, got host {host!r}")
    rest, _, ref = rest.partition("@")
    parts = [p for p in rest.split("/") if p]
    if len(parts) != 2:
        raise ValueError(f"expected https://github.com/owner/repo, got {url!r}")
    owner, repo = parts[0], parts[1].removesuffix(".git")
    if not _OWNER_RE.match(owner) or not _REPO_RE.match(repo) or repo in {".", ".."}:
        raise ValueError(f"invalid owner or repository name in {url!r}")
    if ref and (not _REF_RE.match(ref) or ref.startswith("-") or ".." in ref):
        raise ValueError(f"invalid ref {ref!r}")
    return GitHubRef(owner=owner, repo=repo, ref=ref or None)


def intake(source: str, repos_dir: Path) -> Checkout:
    """Resolve `source` to a checkout: clone or reuse for a GitHub URL, as-is for a local path."""
    if is_url(source):
        ref = parse_github_url(source)
        dest = repos_dir / ref.folder_name
        sha, reused = clone_or_reuse(ref.clone_url, dest, ref.ref)
        return Checkout(root=dest, repo=ref.repo, commit_sha=sha, source=source, reused=reused)
    root = Path(source).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"not a directory: {source}")
    return Checkout(root=root, repo=root.name, commit_sha=head_sha(root), source=source)


def clone_or_reuse(clone_url: str, dest: Path, ref: str | None = None) -> tuple[str, bool]:
    """Make `dest` a blobless clone of `clone_url` at `ref` (default branch when None).

    Returns the checked-out SHA and whether the existing clone was reused unchanged.
    Separate from URL parsing so tests can point it at a local repository.
    """
    if (dest / ".git").exists():
        local = head_sha(dest)
        remote = _remote_sha(clone_url, ref)
        if local is not None and local == remote:
            return local, True
        run_git(["fetch", "--filter=blob:none", "origin", ref or "HEAD"], cwd=dest)
        run_git(["checkout", "--force", "--detach", "FETCH_HEAD"], cwd=dest)
    else:
        if dest.exists() and any(dest.iterdir()):
            raise RuntimeError(f"{dest} exists but is not a git clone; delete it and retry")
        dest.parent.mkdir(parents=True, exist_ok=True)
        args = ["clone", "--filter=blob:none", "--single-branch", "--no-recurse-submodules"]
        if ref:
            args += ["--branch", ref]
        run_git([*args, "--", clone_url, str(dest.resolve())], cwd=dest.parent)
    sha = head_sha(dest)
    if sha is None:
        raise RuntimeError(f"clone of {clone_url} has no HEAD commit")
    return sha, False


def head_sha(path: Path) -> str | None:
    """Full SHA of HEAD when `path` is inside a git work tree, else None."""
    try:
        out = run_git(["rev-parse", "HEAD"], cwd=path)
    except (RuntimeError, FileNotFoundError):
        return None
    return out.strip() or None


def content_sha(hashes: list[tuple[str, str]]) -> str:
    """A stand-in commit SHA for a folder outside git: a hash of every (path, file hash)."""
    digest = hashlib.sha256()
    for path, sha in sorted(hashes):
        digest.update(f"{path}\0{sha}\n".encode())
    return digest.hexdigest()


def _remote_sha(clone_url: str, ref: str | None) -> str | None:
    """The commit `ref` points to on the remote, without downloading anything."""
    lines = run_git(["ls-remote", "--", clone_url, ref or "HEAD"], cwd=Path.cwd()).splitlines()
    pairs = [line.split("\t", 1) for line in lines if "\t" in line]
    # An annotated tag lists the tag object and, with a `^{}` suffix, the commit it points to.
    peeled = [sha for sha, name in pairs if name.endswith("^{}")]
    if peeled:
        return peeled[0]
    return pairs[0][0] if pairs else None


def run_git(args: list[str], cwd: Path) -> str:
    """Run a read-only or fetch git command; raise RuntimeError with git's message on failure."""
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",  # a private or missing repo fails instead of prompting
        "GIT_LFS_SKIP_SMUDGE": "1",  # never download LFS payloads
    }
    proc = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, check=False
    )
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {args[0]} failed: {message}")
    return proc.stdout.decode("utf-8", errors="replace")
