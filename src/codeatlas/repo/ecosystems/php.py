r"""PHP: `composer.json` packages, path repositories and the PSR-4 autoload map.

The PSR-4 map (`"App\\": "src/"`) says which folder holds which namespace. It is stored
with repo-relative folders so the structural resolver (T16) can turn `use App\User;`
into `src/User.php` without reading `composer.json` again.
"""

from __future__ import annotations

import json

from codeatlas.repo.ecosystems.base import Declared, Found, ManifestError, RepoView, Workspace
from codeatlas.repo.paths import join, parent

ECOSYSTEM = "composer"


def normalize(name: str) -> str:
    """Composer package names are case-insensitive."""
    return name.lower()


def find(view: RepoView) -> Found:
    found = Found()
    for manifest in view.named("composer.json"):
        _composer(view, manifest, found)
    return found


def _composer(view: RepoView, manifest: str, found: Found) -> None:
    root = parent(manifest)
    try:
        data = json.loads(view.read(manifest))
        if not isinstance(data, dict):
            raise ManifestError(f"{manifest}: expected a JSON object")
    except (ManifestError, json.JSONDecodeError) as exc:
        warning = f"{manifest}: cannot parse: {exc}"
        found.packages.append(
            Declared(ECOSYSTEM, view.folder_name(root), manifest, root, warnings=[warning])
        )
        return
    name = data.get("name")
    declared = Declared(
        ECOSYSTEM, name if isinstance(name, str) and name else view.folder_name(root),
        manifest, root,
    )
    if not isinstance(name, str) or not name:
        declared.warnings.append(f"{manifest}: no name; named after its folder")
    version = data.get("version")
    declared.version = version if isinstance(version, str) else None
    for field_name in ("require", "require-dev"):
        requires = data.get(field_name)
        if isinstance(requires, dict):
            declared.dependencies.extend(requires)
    declared.extra["autoload_psr4"] = _psr4(data, root)
    declared.entry_points = _bins(data.get("bin"), root)
    members = _path_repositories(data.get("repositories"))
    if members:
        found.workspaces.append(Workspace(ECOSYSTEM, manifest, root, members))
    found.packages.append(declared)


def _bins(value: object, root: str) -> list[str]:
    """`"bin": "bin/tool"` or `"bin": ["bin/a", "bin/b"]`, as repo-relative paths."""
    names = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    paths = (join(root, n) for n in names if isinstance(n, str))
    return sorted({p for p in paths if p})


def _psr4(data: dict[str, object], root: str) -> dict[str, list[str]]:
    """Namespace prefix -> repo-relative folders, from `autoload` and `autoload-dev`."""
    mapping: dict[str, list[str]] = {}
    for section in ("autoload", "autoload-dev"):
        autoload = data.get(section)
        psr4 = autoload.get("psr-4") if isinstance(autoload, dict) else None
        if not isinstance(psr4, dict):
            continue
        for prefix, folders in psr4.items():
            for folder in [folders] if isinstance(folders, str) else folders or []:
                target = join(root, folder) if isinstance(folder, str) else None
                if target is not None and target not in mapping.setdefault(prefix, []):
                    mapping[prefix].append(target)
    return mapping


def _path_repositories(repositories: object) -> list[str]:
    """`{"type": "path", "url": "packages/*"}` entries: local packages this one can require."""
    if isinstance(repositories, dict):
        entries = list(repositories.values())
    elif isinstance(repositories, list):
        entries = repositories
    else:
        return []
    return [
        entry["url"]
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("type") == "path"
        and isinstance(entry.get("url"), str)
    ]
