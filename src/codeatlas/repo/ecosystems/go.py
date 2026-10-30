"""Go: `go.mod` modules and `go.work` workspaces.

Both files are lists of directives, either one per line (`require x v1`) or grouped in a
block (`require ( ... )`), so one small reader serves both. A module's entry points are
the folders inside it holding a `package main` file.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from codeatlas.repo.ecosystems.base import Declared, Found, ManifestError, RepoView, Workspace
from codeatlas.repo.paths import is_under, join, parent

ECOSYSTEM = "go"
_PACKAGE_MAIN = re.compile(rb"^package\s+main\b", re.MULTILINE)
# The package clause sits after the license header, well inside the first few kilobytes.
_HEAD_BYTES = 16_384


def find(view: RepoView) -> Found:
    found = Found()
    for manifest in view.named("go.mod"):
        found.packages.append(_go_mod(view, manifest))
    roots = [p.root for p in found.packages]
    for package in found.packages:
        package.entry_points = _main_folders(view, package.root, roots)
    for manifest in view.named("go.work"):
        found.workspaces.append(_go_work(view, manifest))
    return found


def directives(text: str) -> Iterator[tuple[str, list[str]]]:
    """(directive, arguments) per line, with `//` comments and quotes removed."""
    block: str | None = None
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        if block is not None:
            if line == ")":
                block = None
            else:
                yield block, _args(line)
            continue
        word, _, rest = line.partition(" ")
        rest = rest.strip()
        if rest == "(":
            block = word
        else:
            yield word, _args(rest)


def _args(text: str) -> list[str]:
    return [a.strip('"`') for a in text.split()]


def _go_mod(view: RepoView, manifest: str) -> Declared:
    root = parent(manifest)
    package = Declared(ECOSYSTEM, view.folder_name(root), manifest, root)
    try:
        text = view.read(manifest)
    except ManifestError as exc:
        package.warnings.append(str(exc))
        return package
    module_path = None
    for directive, args in directives(text):
        if directive == "module" and args:
            module_path = args[0]
        elif directive == "require" and args:
            package.dependencies.append(args[0])
        elif directive == "replace" and "=>" in args:
            # `replace example.com/lib => ../lib` points at a folder in this repository.
            target = args[args.index("=>") + 1 :]
            if target and target[0].startswith((".", "/")):
                folder = join(root, target[0])
                if folder is not None:
                    package.path_dependencies.append(folder)
    if module_path is None:
        package.warnings.append(f"{manifest}: no module directive; named after its folder")
    else:
        package.name = module_path
        package.extra["module_path"] = module_path
    return package


def _main_folders(view: RepoView, root: str, module_roots: list[str]) -> list[str]:
    """Folders of this module (not of a nested one) with a non-test `package main` file."""
    nested = [r for r in module_roots if r != root and is_under(r, root)]
    folders: set[str] = set()
    for path in view.under(root):
        if not path.endswith(".go") or path.endswith("_test.go"):
            continue
        folder = parent(path)
        if folder in folders or any(is_under(path, r) for r in nested):
            continue
        try:
            with view.root.joinpath(*path.split("/")).open("rb") as handle:
                head = handle.read(_HEAD_BYTES)
        except OSError:
            continue
        if _PACKAGE_MAIN.search(head):
            folders.add(folder)
    return sorted(folders)


def _go_work(view: RepoView, manifest: str) -> Workspace:
    workspace = Workspace(ECOSYSTEM, manifest, parent(manifest))
    try:
        text = view.read(manifest)
    except ManifestError as exc:
        workspace.warnings.append(str(exc))
        return workspace
    for directive, args in directives(text):
        if directive == "use" and args:
            workspace.members.append(args[0])
    return workspace
