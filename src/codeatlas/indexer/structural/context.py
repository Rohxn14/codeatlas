"""What the resolver knows about the repository, built once per run from parse results.

Resolvers receive `ParseResult`s, not a database, so the lookups they need (a file's
definitions by name, the files of a directory or package) are built here in one pass.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from codeatlas.indexer.adapter import SymbolIndex
from codeatlas.models import Node, NodeKind, ParseResult, RawImport

PathTable = dict[tuple[str, str], list[str]]  # (language, key) -> file paths


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
        return str(PurePosixPath(self.path).parent).removeprefix(".")

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

    @classmethod
    def build(cls, results: list[ParseResult], index: SymbolIndex | None) -> Context:
        ctx = cls(index)
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


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
