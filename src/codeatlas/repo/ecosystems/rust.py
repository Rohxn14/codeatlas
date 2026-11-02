"""Rust: `Cargo.toml` crates and `[workspace]` tables.

A workspace root without `[package]` (a "virtual manifest") lists members but is not a
crate itself. A dependency is internal when it has a `path`, or when its name matches a
crate in the repository (which covers `{ workspace = true }`).
"""

from __future__ import annotations

import tomllib

from codeatlas.repo.ecosystems.base import (
    Declared,
    Found,
    ManifestError,
    RepoView,
    Workspace,
    guarded,
)
from codeatlas.repo.paths import basename, child, join, parent

ECOSYSTEM = "cargo"
_DEPENDENCY_TABLES = ("dependencies", "dev-dependencies", "build-dependencies")


def normalize(name: str) -> str:
    """Cargo treats `-` and `_` in crate names as the same."""
    return name.replace("_", "-").lower()


def find(view: RepoView) -> Found:
    found = Found()
    for manifest in view.named("Cargo.toml"):
        guarded(view, ECOSYSTEM, manifest, found,
                lambda m=manifest: _cargo_toml(view, m, found))
    return found


def _cargo_toml(view: RepoView, manifest: str, found: Found) -> None:
    root = parent(manifest)
    try:
        data = tomllib.loads(view.read(manifest))
    except (ManifestError, tomllib.TOMLDecodeError) as exc:
        warning = f"{manifest}: cannot parse: {exc}"
        found.packages.append(
            Declared(ECOSYSTEM, view.folder_name(root), manifest, root, warnings=[warning])
        )
        return
    workspace = data.get("workspace")
    if isinstance(workspace, dict):
        found.workspaces.append(
            Workspace(
                ECOSYSTEM, manifest, root, _strings(workspace.get("members")),
                _strings(workspace.get("exclude")),
            )
        )
    package = data.get("package")
    if not isinstance(package, dict):
        if not isinstance(workspace, dict):
            warning = f"{manifest}: neither [package] nor [workspace]; named after its folder"
            found.packages.append(
                Declared(ECOSYSTEM, view.folder_name(root), manifest, root, warnings=[warning])
            )
        return
    name = package.get("name")
    declared = Declared(
        ECOSYSTEM,
        name if isinstance(name, str) else view.folder_name(root),
        manifest,
        root,
        package.get("version") if isinstance(package.get("version"), str) else None,
    )
    for table in _dependency_tables(data):
        for key, spec in table.items():
            declared.dependencies.append(key)
            if isinstance(spec, dict):
                if isinstance(spec.get("package"), str):  # `alias = { package = "real" }`
                    declared.dependencies.append(spec["package"])
                if isinstance(spec.get("path"), str):
                    folder = join(root, spec["path"])
                    if folder is not None:
                        declared.path_dependencies.append(folder)
    declared.entry_points = _binaries(view, root, data)
    library = _library(view, root, data)
    if library:
        declared.extra["library"] = library
    found.packages.append(declared)


def _library(view: RepoView, root: str, data: dict[str, object]) -> str | None:
    """The crate's library root: `[lib] path` when declared, else `src/lib.rs` if present."""
    lib = data.get("lib")
    if isinstance(lib, dict) and isinstance(lib.get("path"), str):
        return join(root, lib["path"])
    default = child(root, "src/lib.rs")
    return default if view.exists(default) else None


def _dependency_tables(data: dict[str, object]) -> list[dict[str, object]]:
    """`[dependencies]` and friends, also under `[target.'cfg(...)'.dependencies]`."""
    scopes = [data]
    targets = data.get("target")
    if isinstance(targets, dict):
        scopes.extend(t for t in targets.values() if isinstance(t, dict))
    tables = []
    for scope in scopes:
        for name in _DEPENDENCY_TABLES:
            table = scope.get(name)
            if isinstance(table, dict):
                tables.append(table)
    return tables


def _binaries(view: RepoView, root: str, data: dict[str, object]) -> list[str]:
    """`src/main.rs`, `src/bin/*.rs` and every `[[bin]]` path that exists."""
    found: set[str] = set()
    main = child(root, "src/main.rs")
    if view.exists(main):
        found.add(main)
    bin_folder = child(root, "src/bin")
    for path in view.under(bin_folder):
        if path.endswith(".rs") and (parent(path) == bin_folder or basename(path) == "main.rs"):
            found.add(path)
    bins = data.get("bin")
    for entry in bins if isinstance(bins, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            path = join(root, entry["path"])
            if path is not None:
                found.add(path)
    return sorted(found)


def _strings(value: object) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []
