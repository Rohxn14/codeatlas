"""Maven: `pom.xml` modules, named `groupId:artifactId`.

A module usually inherits its `groupId` and `version` from `<parent>`, and dependencies
often write `${project.groupId}`, so both are filled in before names are compared. Only
`<project><dependencies>` counts: `<dependencyManagement>` pins versions without adding
a dependency.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from codeatlas.repo.ecosystems.base import (
    Declared,
    Found,
    ManifestError,
    RepoView,
    Workspace,
    guarded,
)
from codeatlas.repo.paths import parent

ECOSYSTEM = "maven"
_PROPERTY = re.compile(r"\$\{([^}]+)\}")


def find(view: RepoView) -> Found:
    found = Found()
    for manifest in view.named("pom.xml"):
        guarded(view, ECOSYSTEM, manifest, found, lambda m=manifest: _pom(view, m, found))
    return found


def _pom(view: RepoView, manifest: str, found: Found) -> None:
    root = parent(manifest)
    try:
        project = _strip_namespaces(ET.fromstring(view.read(manifest)))
    except (ManifestError, ET.ParseError) as exc:
        warning = f"{manifest}: cannot parse: {exc}"
        found.packages.append(
            Declared(ECOSYSTEM, view.folder_name(root), manifest, root, warnings=[warning])
        )
        return
    parent_pom = project.find("parent")
    group = _text(project, "groupId") or _text(parent_pom, "groupId")
    artifact = _text(project, "artifactId")
    version = _text(project, "version") or _text(parent_pom, "version")
    properties = _properties(project, group, artifact, version)
    group, artifact, version = (_expand(v, properties) for v in (group, artifact, version))
    declared = Declared(
        ECOSYSTEM, _coordinates(group, artifact) or view.folder_name(root), manifest, root, version
    )
    if not artifact:
        declared.warnings.append(f"{manifest}: no artifactId; named after its folder")
    declared.extra.update({"group_id": group, "artifact_id": artifact})
    for dependency in project.findall("dependencies/dependency"):
        dep_artifact = _expand(_text(dependency, "artifactId"), properties)
        dep_group = _expand(_text(dependency, "groupId"), properties)
        coordinates = _coordinates(dep_group, dep_artifact)
        if coordinates:
            declared.dependencies.append(coordinates)
    modules = [m.text.strip() for m in project.findall("modules/module") if m.text]
    if modules:
        found.workspaces.append(Workspace(ECOSYSTEM, manifest, root, modules))
    found.packages.append(declared)


def _coordinates(group: str | None, artifact: str | None) -> str | None:
    if not artifact:
        return None
    return f"{group}:{artifact}" if group else artifact


def _strip_namespaces(element: ET.Element) -> ET.Element:
    """`{http://maven.apache.org/POM/4.0.0}artifactId` -> `artifactId`, for simple paths."""
    for node in element.iter():
        if isinstance(node.tag, str) and "}" in node.tag:
            node.tag = node.tag.split("}", 1)[1]
    return element


def _text(element: ET.Element | None, tag: str) -> str | None:
    if element is None:
        return None
    found = element.find(tag)
    if found is None or not found.text:
        return None
    return found.text.strip() or None


def _properties(
    project: ET.Element, group: str | None, artifact: str | None, version: str | None
) -> dict[str, str]:
    values = {
        key: value
        for key, value in {
            "project.groupId": group, "groupId": group, "pom.groupId": group,
            "project.artifactId": artifact, "project.version": version,
            "version": version, "pom.version": version,
        }.items()
        if value
    }
    props = project.find("properties")
    if props is not None:
        for prop in props:
            if isinstance(prop.tag, str) and prop.text:
                values[prop.tag] = prop.text.strip()
    return values


def _expand(value: str | None, properties: dict[str, str]) -> str | None:
    """Fill in `${name}` from the pom's own properties; unknown ones stay as written."""
    if value is None:
        return None
    return _PROPERTY.sub(lambda m: properties.get(m.group(1), m.group(0)), value)
