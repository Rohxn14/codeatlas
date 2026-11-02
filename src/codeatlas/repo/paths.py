"""Repo-relative path helpers shared by the repository analyzers.

Every path here is a forward-slash string relative to the repository root, the same form
`FileRecord.path` uses. The repository root itself is the empty string `""`, so joining
needs no special case: `join("", "a")` is `"a"`.
"""

from __future__ import annotations

import re
from functools import lru_cache

from codeatlas.models import make_key, make_node_id


def module_id(snapshot_id: str, path: str) -> str:
    """Id of a file's module node, which the adapters create with the same helpers."""
    return make_node_id(snapshot_id, make_key(path, ""))


def repo_name(snapshot_id: str) -> str:
    """The repository part of `{repo}@{sha}`."""
    return snapshot_id.rsplit("@", 1)[0]


def parent(path: str) -> str:
    """Folder of a path: `a/b/c.txt` -> `a/b`, `c.txt` -> `""`."""
    return path.rsplit("/", 1)[0] if "/" in path else ""


def basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def child(folder: str, name: str) -> str:
    """`folder/name`, or just `name` at the repository root."""
    return f"{folder}/{name}" if folder else name


def join(base: str, relative: str) -> str | None:
    """`base/relative` with `.` and `..` resolved, or None when it leaves the repository.

    Manifests write paths as their authors like them (`./lib`, `..\\Core\\Core.csproj`),
    so backslashes become slashes and a trailing slash is dropped.
    """
    parts = base.split("/") if base else []
    for part in relative.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts)


def is_under(path: str, folder: str) -> bool:
    """True when `path` is `folder` or inside it; everything is under the root `""`."""
    return not folder or path == folder or path.startswith(folder + "/")


def glob_matches(pattern: str, path: str) -> bool:
    """Workspace-member glob matching: `*` stays inside one folder, `**` crosses folders."""
    return _glob_regex(pattern).fullmatch(path) is not None


@lru_cache(maxsize=512)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    pattern = join("", pattern) or ""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))
