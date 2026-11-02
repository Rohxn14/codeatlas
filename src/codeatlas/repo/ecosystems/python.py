"""Python: `pyproject.toml` (`[project]` or `[tool.poetry]`), `setup.cfg`, `setup.py`.

`setup.py` is a program, so it is never run: a regex looks for a literal `name="..."`.
When one folder has several of these files, the first that names the package wins, in
the order pyproject.toml, setup.cfg, setup.py.
"""

from __future__ import annotations

import configparser
import re
import tomllib

from codeatlas.repo.ecosystems.base import (
    Declared,
    Found,
    ManifestError,
    RepoView,
    Workspace,
    guarded,
)
from codeatlas.repo.paths import child, join, parent

ECOSYSTEM = "pypi"
_MANIFESTS = ("pyproject.toml", "setup.cfg", "setup.py")
# The distribution name at the start of a PEP 508 requirement: `requests[socks]>=2` -> requests.
_REQUIREMENT_NAME = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_SETUP_PY_FIELD = r"""\b{field}\s*=\s*["']([^"']+)["']"""


def normalize(name: str) -> str:
    """PEP 503: `My_Package` and `my-package` are the same distribution."""
    return re.sub(r"[-_.]+", "-", name).lower()


def find(view: RepoView) -> Found:
    found = Found()
    folders = sorted({parent(p) for p in view.named(*_MANIFESTS)})
    for folder in folders:
        guarded(view, ECOSYSTEM, _first_manifest(view, folder), found,
                lambda f=folder: _folder(view, f, found))
    return found


def _folder(view: RepoView, folder: str, found: Found) -> None:
    """The package (if any) declared by the Python manifests in one folder."""
    package, warnings = None, []
    is_package = False
    for filename in _MANIFESTS:
        manifest = child(folder, filename)
        if not view.exists(manifest):
            continue
        result, claims_package = _PARSERS[filename](view, manifest, found, warnings)
        is_package = is_package or claims_package
        if package is None and result is not None:
            package = result
    if package is None and is_package:
        name = view.folder_name(folder)
        warnings.append(f"{folder or '.'}: no literal package name; named after its folder")
        package = Declared(ECOSYSTEM, name, _first_manifest(view, folder), folder)
    if package is not None:
        package.warnings.extend(warnings)
        found.packages.append(package)
    elif warnings:
        # Not a package, but the problem must still surface: the orchestrator files
        # workspace warnings on the package that contains the manifest.
        found.workspaces.append(
            Workspace(ECOSYSTEM, _first_manifest(view, folder), folder, warnings=warnings)
        )


def _first_manifest(view: RepoView, folder: str) -> str:
    present = [child(folder, f) for f in _MANIFESTS if view.exists(child(folder, f))]
    return present[0]


def _pyproject(
    view: RepoView, manifest: str, found: Found, warnings: list[str]
) -> tuple[Declared | None, bool]:
    """A package from `[project]` or `[tool.poetry]`, and whether the file claims one."""
    try:
        data = tomllib.loads(view.read(manifest))
    except (ManifestError, tomllib.TOMLDecodeError) as exc:
        warnings.append(f"{manifest}: cannot parse: {exc}")
        return None, True
    root = parent(manifest)
    tool = _table(data, "tool")
    project, poetry = _table(data, "project"), _table(tool, "poetry")
    uv = _table(tool, "uv")
    workspace = _table(uv, "workspace")
    if workspace:
        found.workspaces.append(
            Workspace(
                ECOSYSTEM, manifest, root, _strings(workspace.get("members")),
                _strings(workspace.get("exclude")),
            )
        )
    claims = bool(project or poetry or "build-system" in data)
    name = project.get("name") or poetry.get("name")
    if not isinstance(name, str) or not name:
        return None, claims
    version = project.get("version") or poetry.get("version")
    package = Declared(ECOSYSTEM, name, manifest, root)
    package.version = version if isinstance(version, str) else None
    package.dependencies = _pep508_names(project) + _poetry_names(poetry)
    package.path_dependencies = _path_sources(root, _table(uv, "sources"), poetry)
    package.entry_points = _scripts(project, poetry)
    return package, True


def _pep508_names(project: dict[str, object]) -> list[str]:
    requirements = _strings(project.get("dependencies"))
    for extra in _table(project, "optional-dependencies").values():
        requirements.extend(_strings(extra))
    names = []
    for requirement in requirements:
        match = _REQUIREMENT_NAME.match(requirement)
        if match:
            names.append(match.group(1))
    return names


def _poetry_names(poetry: dict[str, object]) -> list[str]:
    tables = [_table(poetry, "dependencies"), _table(poetry, "dev-dependencies")]
    for group in _table(poetry, "group").values():
        if isinstance(group, dict):
            tables.append(_table(group, "dependencies"))
    return [name for table in tables for name in table if name != "python"]


def _path_sources(root: str, uv_sources: dict[str, object], poetry: dict[str, object]) -> list[str]:
    """Folders named by `{ path = "../lib" }` in uv sources or poetry dependencies."""
    specs = list(uv_sources.values()) + list(_table(poetry, "dependencies").values())
    paths = []
    for spec in specs:
        if isinstance(spec, dict) and isinstance(spec.get("path"), str):
            target = join(root, spec["path"])
            if target is not None:
                paths.append(target)
    return paths


def _scripts(project: dict[str, object], poetry: dict[str, object]) -> list[str]:
    tables = (_table(project, "scripts"), _table(project, "gui-scripts"), _table(poetry, "scripts"))
    return sorted(f"{k} = {v}" for t in tables for k, v in t.items() if isinstance(v, str))


def _setup_cfg(
    view: RepoView, manifest: str, found: Found, warnings: list[str]
) -> tuple[Declared | None, bool]:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(view.read(manifest), source=manifest)
    except (ManifestError, configparser.Error) as exc:
        warnings.append(f"{manifest}: cannot parse: {exc}")
        return None, True
    name = parser.get("metadata", "name", fallback="").strip()
    if not name:
        return None, False  # often only tool settings ([flake8], [tool:pytest])
    version = parser.get("metadata", "version", fallback="").strip() or None
    package = Declared(ECOSYSTEM, name, manifest, parent(manifest), version)
    requirements = parser.get("options", "install_requires", fallback="").splitlines()
    if parser.has_section("options.extras_require"):
        for _, value in parser.items("options.extras_require"):
            requirements.extend(value.splitlines())
    for requirement in requirements:
        match = _REQUIREMENT_NAME.match(requirement)
        if match:
            package.dependencies.append(match.group(1))
    scripts = parser.get("options.entry_points", "console_scripts", fallback="")
    package.entry_points = sorted(s.strip() for s in scripts.splitlines() if "=" in s)
    return package, True


def _setup_py(
    view: RepoView, manifest: str, found: Found, warnings: list[str]
) -> tuple[Declared | None, bool]:
    try:
        text = view.read(manifest)
    except ManifestError as exc:
        warnings.append(str(exc))
        return None, True
    name = re.search(_SETUP_PY_FIELD.format(field="name"), text)
    if name is None:
        return None, True
    version = re.search(_SETUP_PY_FIELD.format(field="version"), text)
    return Declared(
        ECOSYSTEM, name.group(1), manifest, parent(manifest), version.group(1) if version else None
    ), True


_PARSERS = {"pyproject.toml": _pyproject, "setup.cfg": _setup_cfg, "setup.py": _setup_py}


def _table(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _strings(value: object) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []
