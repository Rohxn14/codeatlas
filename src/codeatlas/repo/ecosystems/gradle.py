"""Gradle: projects from `settings.gradle(.kts)`, dependencies from `build.gradle(.kts)`.

Gradle build files are programs (Groovy or Kotlin), so they are read with regexes and
never run. A settings file's `include(":app", ":lib:core")` names the projects; each is a
package named by its project path, rooted at `app/` and `lib/core/`. A build file no
settings file accounts for is a single-project build of its own.

A build file names another project either by path, `project(":lib:core")`, or through a
type-safe accessor, `projects.lib.core`, where each path segment is camel-cased
(`:retrofit-converters:moshi` is `projects.retrofitConverters.moshi`).
"""

from __future__ import annotations

import re

from codeatlas.repo.ecosystems.base import Declared, Found, ManifestError, RepoView, Workspace
from codeatlas.repo.paths import child, parent

ECOSYSTEM = "gradle"
_SETTINGS = ("settings.gradle", "settings.gradle.kts")
_BUILD = ("build.gradle", "build.gradle.kts")

# `include(":a",\n ":b")` may span lines inside parentheses; `include ':a', ':b'` may not.
_INCLUDE = re.compile(r"^\s*include\b\s*(\([^)]*\)|[^\n]*)", re.MULTILINE)
_QUOTED = re.compile(r"""["']([^"']+)["']""")
_ROOT_NAME = re.compile(r"""rootProject\.name\s*=\s*["']([^"']+)["']""")
_PROJECT_DEPENDENCY = re.compile(r"""project\s*\(\s*(?:path\s*[:=]\s*)?["'](:[^"']*)["']""")
_VERSION = re.compile(r"""^\s*version\s*=?\s*["']([^"']+)["']""", re.MULTILINE)
_MAIN_CLASS = re.compile(r"""mainClass(?:Name)?\s*(?:\.set\s*\(|=)?\s*["']([^"']+)["']""")
_ACCESSOR = re.compile(r"\bprojects((?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
_ACCESSOR_PREFIX = "projects."
_SEPARATOR = re.compile(r"[-_]+([A-Za-z0-9])")  # kebab-case and snake_case -> camelCase


def find(view: RepoView) -> Found:
    found = Found()
    claimed: set[str] = set()  # folders some settings file declares as a project
    for settings in view.named(*_SETTINGS):
        _settings(view, settings, found, claimed)
    for build in view.named(*_BUILD):
        folder = parent(build)
        if folder not in claimed:
            claimed.add(folder)
            found.packages.append(_project(view, view.folder_name(folder), ":", folder, build))
    _resolve_accessors(found.packages)
    return found


def _settings(view: RepoView, settings: str, found: Found, claimed: set[str]) -> None:
    root = parent(settings)
    workspace = Workspace(ECOSYSTEM, settings, root)
    found.workspaces.append(workspace)
    try:
        text = view.read(settings)
    except ManifestError as exc:
        workspace.warnings.append(str(exc))
        return
    root_name = _ROOT_NAME.search(text)
    projects = {":": root}
    for line in _INCLUDE.finditer(text):
        for path in _QUOTED.findall(line.group(1)):
            gradle_path = path if path.startswith(":") else f":{path}"
            projects[gradle_path] = child(root, gradle_path.strip(":").replace(":", "/"))
    for gradle_path, folder in projects.items():
        if folder in claimed:
            continue
        claimed.add(folder)
        name = gradle_path
        if gradle_path == ":":
            name = root_name.group(1) if root_name else view.folder_name(root)
        else:
            workspace.members.append(folder[len(root) + 1 :] if root else folder)
        build = next((child(folder, b) for b in _BUILD if view.exists(child(folder, b))), None)
        found.packages.append(_project(view, name, gradle_path, folder, build or settings))


def _project(view: RepoView, name: str, gradle_path: str, folder: str, manifest: str) -> Declared:
    declared = Declared(ECOSYSTEM, name, manifest, folder)
    declared.extra["gradle_path"] = gradle_path
    if manifest.endswith(_SETTINGS):
        return declared  # no build file of its own: nothing more to read
    try:
        text = view.read(manifest)
    except ManifestError as exc:
        declared.warnings.append(str(exc))
        return declared
    declared.dependencies = _PROJECT_DEPENDENCY.findall(text)
    declared.dependencies += [_ACCESSOR_PREFIX + a[1:] for a in _ACCESSOR.findall(text)]
    version = _VERSION.search(text)
    declared.version = version.group(1) if version else None
    declared.entry_points = sorted(set(_MAIN_CLASS.findall(text)))
    return declared


def _resolve_accessors(packages: list[Declared]) -> None:
    """Replace `projects.a.bC` with the project path it names, `:a:b-c`, once every
    project is known; an accessor naming no project is dropped."""
    by_accessor = {
        _accessor(str(p.extra["gradle_path"])): str(p.extra["gradle_path"])
        for p in packages
        if p.extra.get("gradle_path") != ":"
    }
    for package in packages:
        resolved = []
        for dependency in package.dependencies:
            if not dependency.startswith(_ACCESSOR_PREFIX):
                resolved.append(dependency)
                continue
            # `projects.core.dependencyProject` still names `:core`: try shorter prefixes.
            parts = dependency.removeprefix(_ACCESSOR_PREFIX).split(".")
            for end in range(len(parts), 0, -1):
                path = by_accessor.get(".".join(parts[:end]))
                if path:
                    resolved.append(path)
                    break
        package.dependencies = resolved


def _accessor(gradle_path: str) -> str:
    """`:retrofit-converters:moshi` -> `retrofitConverters.moshi`."""
    segments = gradle_path.strip(":").split(":")
    return ".".join(_SEPARATOR.sub(lambda m: m.group(1).upper(), s) for s in segments)
