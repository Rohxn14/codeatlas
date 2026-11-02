"""What an ecosystem parser reads (`RepoView`) and what it reports (`Declared`, `Workspace`).

Each ecosystem module has one function, `find(view) -> Found`. It picks its own manifests
from the file list, parses them without running anything, and reports the packages they
declare. Matching dependencies to packages, workspace membership and file ownership are
the same for every ecosystem, so `repo/manifests.py` does them once.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from codeatlas.models import FileRecord, make_key
from codeatlas.repo.paths import basename, is_under, parent

# Manifests are small; anything larger is not a manifest anyone wrote by hand.
MAX_MANIFEST_BYTES = 2_000_000


@dataclass(slots=True)
class Declared:
    """One package a manifest declares, before it becomes a PACKAGE node."""

    ecosystem: str
    name: str
    manifest: str
    root: str
    version: str | None = None
    # Names as written in the manifest; only those naming a package in this repository
    # become DEPENDS_ON edges.
    dependencies: list[str] = field(default_factory=list)
    # Repo-relative folders or manifest paths a dependency points at (`file:../x`,
    # `path = "../x"`, `<ProjectReference>`).
    path_dependencies: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    extra: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        """The PACKAGE node key: `{manifest}::package:{name}` (contract section 4)."""
        return make_key(self.manifest, f"package:{self.name}")


@dataclass(slots=True)
class Workspace:
    """A manifest that lists member packages: npm `workspaces`, `go.work`, a `.sln`, ...

    `members` are globs relative to `root`. Some workspaces are also packages (a root
    `package.json` with a name); others are not (`pnpm-workspace.yaml`, `go.work`).
    """

    ecosystem: str
    manifest: str
    root: str
    members: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Found:
    packages: list[Declared] = field(default_factory=list)
    workspaces: list[Workspace] = field(default_factory=list)


class ManifestError(Exception):
    """A manifest could not be read or parsed; the message becomes a warning."""


class RepoView:
    """The file list plus read access, so parsers never touch paths outside the snapshot."""

    def __init__(self, root: Path, files: Sequence[FileRecord], repo: str) -> None:
        self.root = root
        self.repo = repo
        self.paths: list[str] = sorted(f.path for f in files)
        self._present = set(self.paths)

    def exists(self, path: str) -> bool:
        return path in self._present

    def named(self, *names: str) -> list[str]:
        """Paths whose file name is one of `names`."""
        wanted = set(names)
        return [p for p in self.paths if basename(p) in wanted]

    def with_suffix(self, *suffixes: str) -> list[str]:
        return [p for p in self.paths if p.lower().endswith(suffixes)]

    def under(self, folder: str) -> list[str]:
        return [p for p in self.paths if is_under(p, folder)]

    def read(self, path: str, limit: int = MAX_MANIFEST_BYTES) -> str:
        """Text of a file in the snapshot; raises ManifestError instead of OSError."""
        full = self.root.joinpath(*path.split("/"))
        try:
            with full.open("rb") as handle:
                data = handle.read(limit + 1)
        except OSError as exc:
            raise ManifestError(f"{path}: cannot read: {exc.strerror or exc}") from exc
        if len(data) > limit:
            raise ManifestError(f"{path}: larger than {limit} bytes, not read")
        # utf-8-sig drops the byte-order mark Visual Studio writes into .csproj files.
        return data.decode("utf-8-sig", errors="replace")

    def folder_name(self, folder: str) -> str:
        """A name for a package whose manifest gives none: its folder, or the repository."""
        return basename(folder) if folder else self.repo


def guarded(
    view: RepoView,
    ecosystem: str,
    manifest: str,
    found: Found,
    parse: Callable[[], None],
    workspace_only: bool = False,
) -> None:
    """Run one manifest's parser so that a bug in it costs only that manifest.

    Parsers turn malformed files into warnings themselves; this catches what they did
    not expect (a value of the wrong type deep inside a valid file, say). Anything the
    failed parse had added is removed, and the manifest still produces its own
    folder-named package carrying the error, so its files are not handed to another
    package and the warning lands where it belongs. A manifest that only lists members
    (`pnpm-workspace.yaml`, `go.work`, a `.sln`) yields a workspace with the warning.
    """
    packages, workspaces = len(found.packages), len(found.workspaces)
    try:
        parse()
    except Exception as exc:  # defensive by design: see the docstring
        del found.packages[packages:]
        del found.workspaces[workspaces:]
        warning = f"{manifest}: analysis failed: {type(exc).__name__}: {exc}"
        root = parent(manifest)
        if workspace_only:
            found.workspaces.append(Workspace(ecosystem, manifest, root, warnings=[warning]))
        else:
            found.packages.append(
                Declared(ecosystem, view.folder_name(root), manifest, root, warnings=[warning])
            )
