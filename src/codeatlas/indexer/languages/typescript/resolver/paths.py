"""Repo-relative path arithmetic shared by module resolution (forward slashes only)."""

from __future__ import annotations

import posixpath

TS_EXTENSIONS = (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs")
_JS_TO_TS = {
    ".js": (".ts", ".tsx", ".d.ts"),
    ".jsx": (".tsx", ".ts"),
    ".mjs": (".mts", ".ts"),
    ".cjs": (".cts", ".ts"),
}


def join(directory: str, relative: str) -> str | None:
    """`directory/relative` normalised; None if it climbs out of the repository."""
    joined = posixpath.normpath(posixpath.join(directory, relative))
    if joined == ".":
        return ""
    return None if joined.startswith("..") or joined.startswith("/") else joined


def parent(path: str) -> str:
    return posixpath.dirname(path)


def under(path: str, directory: str) -> bool:
    return directory == "" or path == directory or path.startswith(directory + "/")


def file_candidates(base: str) -> list[str]:
    """Paths TypeScript would try for `base`, in order: as written, with an extension,
    a `.js` name standing for its `.ts` source, then `base/index.*`."""
    found = [base]
    found += [base + ext for ext in TS_EXTENSIONS]
    stem, dot, ext = base.rpartition(".")
    if dot and "." + ext in _JS_TO_TS:
        found += [stem + swap for swap in _JS_TO_TS["." + ext]]
    found += [f"{base}/index{ext}" for ext in TS_EXTENSIONS]
    return found
