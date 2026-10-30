"""npm, yarn and pnpm: `package.json` and `pnpm-workspace.yaml`."""

from __future__ import annotations

import json

import yaml

from codeatlas.repo.ecosystems.base import Declared, Found, ManifestError, RepoView, Workspace
from codeatlas.repo.paths import join, parent

ECOSYSTEM = "npm"
_DEPENDENCY_FIELDS = (
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
)
# `"lib": "file:../lib"` and `"lib": "link:../lib"` point at a folder, not a registry.
_PATH_PROTOCOLS = ("file:", "link:")


def find(view: RepoView) -> Found:
    found = Found()
    for manifest in view.named("package.json"):
        _package_json(view, manifest, found)
    for manifest in view.named("pnpm-workspace.yaml"):
        found.workspaces.append(_pnpm_workspace(view, manifest))
    return found


def _package_json(view: RepoView, manifest: str, found: Found) -> None:
    root = parent(manifest)
    try:
        data = json.loads(view.read(manifest))
        if not isinstance(data, dict):
            raise ManifestError(f"{manifest}: expected a JSON object")
    except (ManifestError, json.JSONDecodeError) as exc:
        found.packages.append(_unparsed(view, manifest, f"{manifest}: cannot parse: {exc}"))
        return
    members = _workspace_globs(data.get("workspaces"))
    if members:
        found.workspaces.append(Workspace(ECOSYSTEM, manifest, root, *_split_negations(members)))
    name = data.get("name")
    if not isinstance(name, str) or not name:
        if members:
            return  # a nameless workspace root lists packages but is not one
        package = _unparsed(view, manifest, f"{manifest}: no name; named after its folder")
    else:
        package = Declared(ECOSYSTEM, name, manifest, root)
    version = data.get("version")
    package.version = version if isinstance(version, str) else None
    for field_name in _DEPENDENCY_FIELDS:
        deps = data.get(field_name)
        if not isinstance(deps, dict):
            continue
        for dep, spec in deps.items():
            package.dependencies.append(dep)
            if isinstance(spec, str) and spec.startswith(_PATH_PROTOCOLS):
                target = join(root, spec.split(":", 1)[1])
                if target is not None:
                    package.path_dependencies.append(target)
    package.entry_points = _entry_points(data, root)
    found.packages.append(package)


def _entry_points(data: dict[str, object], root: str) -> list[str]:
    targets: list[object] = [data.get("main")]
    bin_field = data.get("bin")
    if isinstance(bin_field, dict):
        targets.extend(bin_field.values())
    else:
        targets.append(bin_field)
    paths = (join(root, t) for t in targets if isinstance(t, str) and t)
    return sorted({p for p in paths if p})


def _workspace_globs(value: object) -> list[str]:
    """`"workspaces": [...]` (npm, yarn) or `{"packages": [...]}` (yarn classic)."""
    if isinstance(value, dict):
        value = value.get("packages")
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str)]


def _split_negations(globs: list[str]) -> tuple[list[str], list[str]]:
    members = [g for g in globs if not g.startswith("!")]
    excludes = [g[1:] for g in globs if g.startswith("!")]
    return members, excludes


def _pnpm_workspace(view: RepoView, manifest: str) -> Workspace:
    workspace = Workspace(ECOSYSTEM, manifest, parent(manifest))
    try:
        data = yaml.safe_load(view.read(manifest)) or {}
    except (ManifestError, yaml.YAMLError) as exc:
        workspace.warnings.append(f"{manifest}: cannot parse: {exc}")
        return workspace
    globs = data.get("packages") if isinstance(data, dict) else None
    if isinstance(globs, list):
        names = [g for g in globs if isinstance(g, str)]
        workspace.members, workspace.excludes = _split_negations(names)
    return workspace


def _unparsed(view: RepoView, manifest: str, warning: str) -> Declared:
    root = parent(manifest)
    return Declared(ECOSYSTEM, view.folder_name(root), manifest, root, warnings=[warning])
