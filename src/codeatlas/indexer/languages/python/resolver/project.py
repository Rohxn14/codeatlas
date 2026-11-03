"""Where a dotted module name lives: the repository's Python files and import roots.

Python decides what `import a.b` means from `sys.path`, which a static tool cannot see.
So we approximate it with a short list of roots (the repository root, `src/`, every
package root T15's manifests found, and the importing file's own folder) and ask which
files exist under them. Nothing here reads a file.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterable


class Project:
    """The set of Python files plus the import roots they may be imported from."""

    def __init__(self, paths: Iterable[str], package_roots: Iterable[str] = ()) -> None:
        self.paths = frozenset(paths)
        roots = {"", "src"}
        for root in package_roots:
            roots.add(root)
            roots.add(posixpath.join(root, "src"))
        self.roots = tuple(sorted(roots))

    def find_module(self, dotted: str, importer: str, own_root: str = "") -> list[str]:
        """Files that `import dotted` may mean, from `importer`, best matches only.

        Several roots can hold a file for one name (two packages each with `utils.py`).
        Matches inside the importer's own package win; otherwise all of them are
        returned and the caller splits its confidence.
        """
        parts = [p for p in dotted.split(".") if p]
        if not parts:
            return []
        # The importer's own folder is a root only for a script folder: inside a package
        # (a folder with `__init__.py`), `import logging` means the standard library,
        # not a sibling `logging.py` (Python 3 has no implicit relative imports).
        folder = posixpath.dirname(importer)
        in_package = posixpath.join(folder, "__init__.py") in self.paths
        roots = self.roots if in_package else (*self.roots, folder)
        found: list[str] = []
        for root in roots:
            for candidate in _candidates(root, parts):
                if candidate in self.paths and candidate not in found:
                    found.append(candidate)
        own = [p for p in found if _under(p, own_root)]
        return own or found

    def relative_module(self, importer: str, level: int, rest: str) -> list[str]:
        """`from ..a import x` in `importer`: climb `level - 1` folders from its package."""
        folder = posixpath.dirname(importer)
        for _ in range(level - 1):
            if not folder:
                return []  # the dots climb out of the repository
            folder = posixpath.dirname(folder)
        parts = [p for p in rest.split(".") if p]
        found = [c for c in _candidates(folder, parts) if c in self.paths]
        return found[:1] if found else []

    def child_module(self, package_file: str, name: str) -> list[str]:
        """`pkg/__init__.py` and `name` give `pkg/name.py` or `pkg/name/__init__.py`."""
        if posixpath.basename(package_file) != "__init__.py":
            return []
        folder = posixpath.dirname(package_file)
        return [c for c in _candidates(folder, [name]) if c in self.paths][:1]


def _candidates(root: str, parts: list[str]) -> list[str]:
    base = posixpath.join(root, *parts) if parts else root
    if not parts:
        return [posixpath.join(base, "__init__.py")]
    return [base + ".py", posixpath.join(base, "__init__.py")]


def _under(path: str, root: str) -> bool:
    return not root or path.startswith(root + "/")
