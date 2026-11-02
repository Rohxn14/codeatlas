"""Part 1 of the repository layer: packages from manifests, with no parser and no build tool.

Each ecosystem module (`repo/ecosystems/`) reads its own manifests and reports the
packages they declare. This module does what is the same for every ecosystem:

1. workspace membership (which packages a workspace manifest lists),
2. file ownership (each file belongs to the package with the deepest root above it),
3. an implicit package at the repository root for files no manifest covers,
4. DEPENDS_ON edges for dependencies that name another package of this repository.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from codeatlas.models import (
    Edge,
    EdgeKind,
    FileRecord,
    Node,
    NodeKind,
    Resolution,
    Span,
    Tier,
    make_node_id,
)
from codeatlas.repo.ecosystems import ECOSYSTEMS, LANGUAGES, normalize
from codeatlas.repo.ecosystems.base import Declared, RepoView, Workspace
from codeatlas.repo.paths import glob_matches, is_under, join, module_id, parent, repo_name

IMPLICIT_ECOSYSTEM = "none"

# Decision D-12: where a manifest sits says whether it is a real package of the repo.
VENDORED_FOLDERS = frozenset({"vendor", "third_party", "node_modules"})
FIXTURE_FOLDERS = frozenset({"test", "tests", "testdata", "fixtures", "__fixtures__"})


def package_role(manifest: str) -> str:
    """`vendored` (someone else's code, committed), `fixture` (test data), or `package`.

    Test fixtures and vendored libraries carry manifests too: indexing CodeAtlas itself
    found 31 packages, 30 of them test samples. They stay as nodes, so nothing vanishes,
    but summaries count real packages only.
    """
    folders = [f.lower() for f in manifest.split("/")[:-1]]
    if any(f in VENDORED_FOLDERS for f in folders):
        return "vendored"
    if any(f in FIXTURE_FOLDERS for f in folders) or manifest.startswith("eval/fixtures/"):
        return "fixture"
    return "package"


@dataclass(slots=True)
class PackageLayout:
    """Every package of a snapshot and the package that owns each file."""

    packages: list[Declared]
    owner: dict[str, Declared]


class ManifestAnalyzer:
    """PACKAGE nodes, CONTAINS edges to modules, and DEPENDS_ON edges between packages."""

    name = "manifests"

    def __init__(self) -> None:
        self.report: dict[str, object] = {}

    def analyze(
        self, repo_root: Path, files: Sequence[FileRecord], snapshot_id: str
    ) -> tuple[list[Node], list[Edge]]:
        layout = find_packages(repo_root, files, repo_name(snapshot_id))
        languages = _package_languages(files, layout.owner)
        nodes = [package_node(p, snapshot_id, languages.get(p.key)) for p in layout.packages]
        edges = [
            Edge(make_node_id(snapshot_id, package.key), module_id(snapshot_id, path),
                 EdgeKind.CONTAINS, 1.0, Resolution.STRUCTURAL)
            for path, package in layout.owner.items()
        ]
        edges += _dependency_edges(layout.packages, snapshot_id)
        self.report = {
            "packages": len(layout.packages),
            "by_ecosystem": dict(sorted(Counter(p.ecosystem for p in layout.packages).items())),
            "internal_dependencies": sum(1 for e in edges if e.kind is EdgeKind.DEPENDS_ON),
            "by_role": dict(sorted(Counter(package_role(p.manifest) for p in layout.packages)
                                   .items())),
            "warnings": [w for p in layout.packages for w in p.warnings],
        }
        return nodes, edges


def find_packages(repo_root: Path, files: Sequence[FileRecord], repo: str) -> PackageLayout:
    """Read every manifest and decide which package owns each file.

    Never raises for a bad manifest: the ecosystem parser turns it into a warning, and a
    bug in a parser becomes a warning on the root package instead of stopping the run.
    """
    view = RepoView(repo_root, files, repo)
    packages: list[Declared] = []
    workspaces: list[Workspace] = []
    for ecosystem in ECOSYSTEMS:
        try:
            found = ecosystem.find(view)
        except Exception as exc:  # defensive: one parser bug must not lose the others
            name = ecosystem.__name__.rsplit(".", 1)[-1]
            workspaces.append(
                Workspace(name, "", "", warnings=[f"{name} manifests: analysis failed: {exc}"])
            )
            continue
        packages.extend(found.packages)
        workspaces.extend(found.workspaces)
    packages = _unique(packages)
    _apply_workspaces(packages, workspaces)
    owner = _assign_files(files, packages)
    uncovered = [f.path for f in files if f.path not in owner]
    if uncovered or not packages:
        implicit = _implicit(repo)
        packages.append(implicit)
        owner.update(dict.fromkeys(uncovered, implicit))
    for workspace in workspaces:
        if workspace.warnings:
            home = _containing(workspace.manifest, packages) or _root_package(packages, repo)
            home.warnings.extend(workspace.warnings)
    return PackageLayout(packages, owner)


def package_node(package: Declared, snapshot_id: str, language: str | None = None) -> Node:
    """The PACKAGE node; its key is `{manifest}::package:{name}` (contract section 4)."""
    key = package.key
    attrs: dict[str, object] = {
        "ecosystem": package.ecosystem,
        "manifest": package.manifest or None,
        "root": package.root,
        "entry_points": list(package.entry_points),
        "role": package_role(package.manifest),
    }
    if package.version:
        attrs["version"] = package.version
    attrs.update(package.extra)
    if package.warnings:
        attrs["warnings"] = list(package.warnings)
    fallback = LANGUAGES.get(package.ecosystem, ("text",))[0]
    return Node(
        id=make_node_id(snapshot_id, key),
        key=key,
        snapshot_id=snapshot_id,
        kind=NodeKind.PACKAGE,
        language=language or fallback,
        name=package.name,
        qualname=f"package:{package.name}",
        path=package.manifest,
        span=Span(1, 1),
        attrs=attrs,
    )


def _implicit(repo: str) -> Declared:
    """The package for files no manifest covers, so every module belongs to one."""
    return Declared(IMPLICIT_ECOSYSTEM, repo, "", "", extra={"implicit": True})


def _unique(packages: list[Declared]) -> list[Declared]:
    """Drop a second package with the same manifest and name: it would repeat a node id."""
    seen: dict[tuple[str, str], Declared] = {}
    for package in packages:
        first = seen.setdefault((package.manifest, package.name), package)
        if first is not package:
            first.warnings.append(f"{package.manifest}: declares {package.name!r} twice")
    return list(seen.values())


def _apply_workspaces(packages: list[Declared], workspaces: list[Workspace]) -> None:
    """Mark each member with its workspace manifest, and the workspace's own package
    (when the manifest is also a package) with the member globs as written."""
    for workspace in workspaces:
        if not workspace.members:
            continue
        members = _rooted(workspace.root, workspace.members)
        excludes = _rooted(workspace.root, workspace.excludes)
        for package in packages:
            if package.ecosystem != workspace.ecosystem:
                continue
            if package.manifest == workspace.manifest:
                package.extra["workspace_members"] = list(workspace.members)
            elif any(glob_matches(m, package.root) for m in members) and not any(
                glob_matches(x, package.root) for x in excludes
            ):
                package.extra.setdefault("workspace", workspace.manifest)


def _rooted(root: str, globs: list[str]) -> list[str]:
    joined = (join(root, g) for g in globs)
    return [g for g in joined if g is not None]


def _assign_files(files: Sequence[FileRecord], packages: list[Declared]) -> dict[str, Declared]:
    """Each file goes to the package with the deepest root above it.

    Two packages can share a root (a `package.json` beside a `pyproject.toml`); then the
    one whose ecosystem matches the file's language wins, else the first in ECOSYSTEMS
    order.
    """
    by_root: dict[str, list[Declared]] = defaultdict(list)
    for package in packages:
        by_root[package.root].append(package)
    owner: dict[str, Declared] = {}
    for record in files:
        folder = parent(record.path)
        while True:
            candidates = by_root.get(folder)
            if candidates:
                owner[record.path] = _prefer(candidates, record.language)
                break
            if not folder:
                break
            folder = parent(folder)
    return owner


def _prefer(candidates: list[Declared], language: str) -> Declared:
    for package in candidates:
        if language in LANGUAGES.get(package.ecosystem, ()):
            return package
    return candidates[0]


def _containing(path: str, packages: list[Declared]) -> Declared | None:
    """The package with the deepest root above `path`."""
    above = [p for p in packages if is_under(path, p.root)]
    return max(above, key=lambda p: len(p.root), default=None)


def _root_package(packages: list[Declared], repo: str) -> Declared:
    """A package rooted at the repository root, creating the implicit one if needed."""
    for package in packages:
        if not package.root:
            return package
    implicit = _implicit(repo)
    packages.append(implicit)
    return implicit


def _package_languages(
    files: Sequence[FileRecord], owner: dict[str, Declared]
) -> dict[str, str]:
    """The most common parsed language in each package, by package key."""
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for record in files:
        if record.tier is not Tier.TEXT and record.path in owner:
            counts[owner[record.path].key][record.language] += 1
    return {key: counter.most_common(1)[0][0] for key, counter in counts.items()}


def _dependency_edges(packages: list[Declared], snapshot_id: str) -> list[Edge]:
    """DEPENDS_ON for dependencies naming, or pointing at, another package of the repo.

    A path (`file:../lib`, `<ProjectReference>`) is exact. A name shared by several
    packages (two example apps both called `demo`) splits the confidence between them.
    """
    by_name: dict[tuple[str, str], list[Declared]] = defaultdict(list)
    by_location: dict[tuple[str, str], list[Declared]] = defaultdict(list)
    for package in packages:
        if package.ecosystem == IMPLICIT_ECOSYSTEM:
            continue
        by_name[(package.ecosystem, normalize(package.ecosystem, package.name))].append(package)
        by_location[(package.ecosystem, package.root)].append(package)
        if package.manifest != package.root:
            by_location[(package.ecosystem, package.manifest)].append(package)
    edges: list[Edge] = []
    for package in packages:
        if package_role(package.manifest) == "vendored":
            continue  # a vendored library's own dependencies say nothing about this repo
        targets: dict[str, tuple[str, int]] = {}  # target key -> (via, candidates)
        for path in package.path_dependencies:
            found = [t for t in by_location[(package.ecosystem, path)]
                     if t is not package and package_role(t.manifest) != "vendored"]
            for target in found:
                targets[target.key] = ("path", len(found))
        for dependency in package.dependencies:
            name = (package.ecosystem, normalize(package.ecosystem, dependency))
            found = [t for t in by_name[name]
                     if t is not package and package_role(t.manifest) != "vendored"]
            if any(t.key in targets for t in found):
                continue  # already linked, more precisely, by its path
            for target in found:
                targets[target.key] = ("name", len(found))
        for target_key, (via, count) in targets.items():
            attrs: dict[str, object] = {"via": via}
            if count > 1:
                attrs["candidates"] = count
            edges.append(
                Edge(make_node_id(snapshot_id, package.key), make_node_id(snapshot_id, target_key),
                     EdgeKind.DEPENDS_ON, 1.0 / count, Resolution.STRUCTURAL, attrs=attrs)
            )
    return edges
