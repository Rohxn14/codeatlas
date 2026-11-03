"""What the resolver knows about the repository, built once per run from parse results.

Resolvers receive `ParseResult`s, not a database, so the lookups they need (a file's
definitions by name, the files of a directory or package) are built here in one pass.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from codeatlas.indexer.adapter import SymbolIndex
from codeatlas.models import Node, NodeKind, ParseResult, RawImport

PathTable = dict[tuple[str, str], list[str]]  # (language, key) -> file paths
MAX_READ_BYTES = 4 * 1024 * 1024  # a build file or source larger than this is not read


@dataclass(slots=True)
class FileInfo:
    """One parsed file, with its definitions indexed by name."""

    path: str
    language: str
    module: Node
    nodes: dict[str, Node]  # by key
    functions: dict[str, list[Node]]  # by name; functions and methods
    types: dict[str, list[Node]]  # classes and interfaces, by name
    imports: tuple[RawImport, ...]
    package: str | None = None
    package_key: str | None = None

    @property
    def directory(self) -> str:
        parent = str(PurePosixPath(self.path).parent)
        return "" if parent == "." else parent

    @property
    def is_test_file(self) -> bool:
        return self.path.endswith("_test.go")


@dataclass(slots=True)
class Context:
    """All files of the languages one resolver run covers."""

    index: SymbolIndex | None
    files: dict[str, FileInfo] = field(default_factory=dict)
    by_directory: PathTable = field(default_factory=lambda: defaultdict(list))
    by_package: PathTable = field(default_factory=lambda: defaultdict(list))
    by_basename: PathTable = field(default_factory=lambda: defaultdict(list))
    functions_by_name: dict[tuple[str, str], list[Node]] = field(
        default_factory=lambda: defaultdict(list)
    )
    owner_of: dict[str, FileInfo] = field(default_factory=dict)  # node key -> its file
    cache: dict[str, object] = field(default_factory=dict)  # per-run scratch for profiles
    root: Path | None = None  # the checkout, for profiles that read build files as text

    @classmethod
    def build(
        cls, results: list[ParseResult], index: SymbolIndex | None, root: Path | None = None
    ) -> Context:
        ctx = cls(index, root=root)
        for result in sorted(results, key=lambda r: r.path):
            if result.nodes:
                ctx._add(result)
        return ctx

    def _add(self, result: ParseResult) -> None:
        module = result.nodes[0]
        info = FileInfo(
            result.path,
            result.language,
            module,
            {n.key: n for n in result.nodes},
            defaultdict(list),
            defaultdict(list),
            result.imports,
            _text(module.attrs.get("package")),
            _text(module.attrs.get("package_key")),
        )
        for node in result.nodes[1:]:
            if node.kind is NodeKind.FUNCTION:
                info.functions[node.name].append(node)
                self.functions_by_name[(result.language, node.name)].append(node)
            elif node.kind in (NodeKind.CLASS, NodeKind.INTERFACE):
                info.types[node.name].append(node)
            self.owner_of[node.key] = info
        self.owner_of[module.key] = info
        self.files[result.path] = info
        self.by_directory[(result.language, info.directory)].append(result.path)
        self.by_basename[(result.language, PurePosixPath(result.path).name)].append(result.path)
        if info.package:
            self.by_package[(result.language, info.package)].append(result.path)

    def file_of(self, node: Node) -> FileInfo | None:
        return self.files.get(node.path)

    def read(self, path: str) -> bytes | None:
        """A repository file's bytes, or None when it is not a plain file inside the root.

        Profiles pass paths taken from the repository (a CMakeLists name, a node's path),
        so they are untrusted: an absolute path, a `..` or a symlink must not let a
        crafted repository make CodeAtlas read files outside its checkout.
        """
        target = _inside(self.root, path) if self.root is not None else None
        if target is None:
            return None
        try:
            if not target.is_file() or target.stat().st_size > MAX_READ_BYTES:
                return None
            return target.read_bytes()
        except OSError:
            return None


def _inside(root: Path, path: str) -> Path | None:
    """`root/path` with symlinks resolved, or None if it is absolute or leaves `root`."""
    pure = PurePosixPath(path.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or Path(path).is_absolute() or Path(path).drive:
        return None
    try:
        base = root.resolve()
        target = (base / pure).resolve()
    except (OSError, RuntimeError):
        return None
    return target if target.is_relative_to(base) else None


def owner_name(node: Node) -> str | None:
    """The class a method belongs to; a Go or Rust method declared away from its type
    has no `owner_key` but keeps the type's name in `attrs["receiver"]`."""
    if node.owner_key is None:
        receiver = node.attrs.get("receiver")
        return receiver if isinstance(receiver, str) else None
    return node.owner_key.split("::", 1)[1].rsplit(".", 1)[-1].split("#", 1)[0]

def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
