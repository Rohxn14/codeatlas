"""Go resolution profile: import paths map to directories through `go.mod` module paths."""

from __future__ import annotations

import re

from codeatlas.indexer.structural.context import Context, FileInfo
from codeatlas.indexer.structural.profile import Profile, Reach
from codeatlas.models import NodeKind, RawImport

_VERSION_SEGMENT = re.compile(r"^v\d+$")
_DOT_VERSION = re.compile(r"\.v\d+$")


class GoProfile(Profile):
    """A package is every non-test `.go` file of one directory.

    The module path comes from the Package node T15 made for each `go.mod` (its
    `module_path` and `root` attrs, which also cover `go.work` members), so an import
    path under a module path is a directory of this repository. Everything else
    (standard library, third-party) is external.
    """

    languages = frozenset({"go"})
    unqualified_is_toplevel = True
    unqualified_uses_package = True

    def reach(self, ctx: Context, file: FileInfo, imp: RawImport) -> Reach:
        directory = self._directory(ctx, imp.target)
        paths = [
            p
            for p in ctx.by_directory.get(("go", directory), [])
            if directory is not None and not ctx.files[p].is_test_file
        ]
        alias = imp.alias
        if not paths:
            return Reach(imp, external=imp.target, binding=_binding(alias, _guess(imp.target)))
        if alias == "_":
            return Reach(imp, tuple(paths), None, None)
        if alias == ".":
            return Reach(imp, tuple(paths), None, None, None, None)
        declared = next((ctx.files[p].package for p in paths if ctx.files[p].package), None)
        return Reach(imp, tuple(paths), None, _binding(alias, declared or _guess(imp.target)))

    def package_scope(self, ctx: Context, file: FileInfo) -> list[str]:
        same = ctx.by_directory.get(("go", file.directory), [])
        return [
            p
            for p in same
            if p != file.path and (file.is_test_file or not ctx.files[p].is_test_file)
        ]

    def _directory(self, ctx: Context, import_path: str) -> str | None:
        """The repository directory an import path names, via the longest module path."""
        best: tuple[int, str] | None = None
        for module_path, root in self._module_table(ctx):
            if import_path == module_path or import_path.startswith(module_path + "/"):
                rest = import_path[len(module_path) :].strip("/")
                directory = "/".join(p for p in (root, rest) if p)
                if best is None or len(module_path) > best[0]:
                    best = (len(module_path), directory)
        return best[1] if best else None

    def _module_table(self, ctx: Context) -> list[tuple[str, str]]:
        table = ctx.cache.get("go_modules")
        if table is None:
            table = ctx.cache["go_modules"] = _go_modules(ctx)
        return table  # type: ignore[return-value]


def _go_modules(ctx: Context) -> list[tuple[str, str]]:
    """(module path, root folder) for each go.mod package that owns a Go file."""
    if ctx.index is None:
        return []
    found: dict[str, tuple[str, str]] = {}
    for info in ctx.files.values():
        if info.language != "go" or not info.package_key or info.package_key in found:
            continue
        package = ctx.index.by_key(info.package_key)
        if package is None or package.kind is not NodeKind.PACKAGE:
            continue
        module_path = package.attrs.get("module_path")
        if isinstance(module_path, str) and module_path:
            root = package.attrs.get("root")
            found[info.package_key] = (module_path, root if isinstance(root, str) else "")
    return list(found.values())


def _binding(alias: str | None, package_name: str) -> str | None:
    if alias in ("_", "."):
        return None
    return alias or package_name


def _guess(import_path: str) -> str:
    """The package name of an import we cannot read: its last path segment, minus versions."""
    segments = import_path.split("/")
    name = segments[-1]
    if _VERSION_SEGMENT.match(name) and len(segments) > 1:
        name = segments[-2]
    return _DOT_VERSION.sub("", name).removeprefix("go-")
