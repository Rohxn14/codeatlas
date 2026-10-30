""".NET: project files (`*.csproj`, `*.fsproj`, `*.vbproj`) and solutions (`*.sln`, `*.slnx`).

Each project file is a package named after the file. `<ProjectReference Include=...>`
gives internal dependencies as paths to other project files, written with backslashes.
A solution lists projects; it is a workspace, not a package.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from codeatlas.repo.ecosystems.base import Declared, Found, ManifestError, RepoView, Workspace
from codeatlas.repo.paths import basename, join, parent

ECOSYSTEM = "nuget"
_PROJECT_SUFFIXES = (".csproj", ".fsproj", ".vbproj")
# Project("{type-guid}") = "Name", "relative\path\Name.csproj", "{project-guid}"
_SLN_PROJECT = re.compile(r'^Project\("[^"]*"\)\s*=\s*"[^"]*",\s*"([^"]+)"', re.MULTILINE)


def normalize(name: str) -> str:
    """Project and package names are case-insensitive in .NET."""
    return name.lower()


def find(view: RepoView) -> Found:
    found = Found()
    for manifest in view.with_suffix(*_PROJECT_SUFFIXES):
        found.packages.append(_project(view, manifest))
    for solution in view.with_suffix(".sln", ".slnx"):
        found.workspaces.append(_solution(view, solution))
    return found


def _project(view: RepoView, manifest: str) -> Declared:
    root = parent(manifest)
    declared = Declared(ECOSYSTEM, basename(manifest).rsplit(".", 1)[0], manifest, root)
    try:
        project = ET.fromstring(view.read(manifest))
    except (ManifestError, ET.ParseError) as exc:
        declared.warnings.append(f"{manifest}: cannot parse: {exc}")
        return declared
    for element in project.iter():
        tag = element.tag.split("}", 1)[-1] if isinstance(element.tag, str) else ""
        text = (element.text or "").strip()
        if tag == "ProjectReference" and element.get("Include"):
            target = join(root, element.get("Include", ""))
            if target is not None:
                declared.path_dependencies.append(target)
        elif tag == "PackageReference" and element.get("Include"):
            declared.dependencies.append(element.get("Include", ""))
        elif tag == "Version" and text and declared.version is None:
            declared.version = text
        elif tag == "OutputType" and text.lower() in ("exe", "winexe"):
            declared.entry_points = [manifest]
        elif tag in ("RootNamespace", "AssemblyName") and text:
            declared.extra[_snake(tag)] = text
    return declared


def _solution(view: RepoView, solution: str) -> Workspace:
    root = parent(solution)
    workspace = Workspace(ECOSYSTEM, solution, root)
    try:
        text = view.read(solution)
        if solution.endswith(".slnx"):
            # <Solution><Project Path="src\App\App.csproj" /></Solution>
            paths = [p.get("Path", "") for p in ET.fromstring(text).iter("Project")]
        else:
            paths = _SLN_PROJECT.findall(text)
    except (ManifestError, ET.ParseError) as exc:
        workspace.warnings.append(f"{solution}: cannot parse: {exc}")
        return workspace
    for path in paths:
        if path.lower().endswith(_PROJECT_SUFFIXES):
            folder = join("", parent(path.replace("\\", "/")))
            if folder is not None:
                workspace.members.append(folder)
    return workspace


def _snake(tag: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", tag).lower()
