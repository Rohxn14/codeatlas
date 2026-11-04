"""In-memory lookups over the parse results: symbols, members, names and exports."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from codeatlas.indexer.languages.typescript.resolver.modules import ModuleResolver
from codeatlas.models import Node, NodeKind, ParseResult, RawCall, RawImport

MAX_HOPS = 5
_SYMBOL_KINDS = frozenset({NodeKind.CLASS, NodeKind.INTERFACE, NodeKind.FUNCTION})


@dataclass(frozen=True, slots=True)
class Found:
    """What an export name leads to: a symbol, or a whole file (a variable, a namespace)."""

    key: str
    is_module: bool = False

    @property
    def path(self) -> str:
        return self.key.partition("::")[0]


@dataclass(slots=True)
class FileInfo:
    path: str
    module_key: str
    top: dict[str, Node] = field(default_factory=dict)
    default: Node | None = None  # `export default class Store`: stored as `Store`
    imports: list[RawImport] = field(default_factory=list)
    calls: list[RawCall] = field(default_factory=list)


class Tables:
    """Everything the resolver looks up, built once from the results."""

    def __init__(self, results: list[ParseResult]) -> None:
        self.files: dict[str, FileInfo] = {}
        self.nodes: dict[str, Node] = {}
        self.members: dict[str, list[Node]] = defaultdict(list)
        self.functions_by_name: dict[str, list[Node]] = defaultdict(list)
        for result in results:
            info = FileInfo(result.path, f"{result.path}::", imports=list(result.imports),
                            calls=list(result.calls))
            self.files[result.path] = info
            for node in result.nodes:
                self.nodes.setdefault(node.key, node)
                self._add(info, node)

    def _add(self, info: FileInfo, node: Node) -> None:
        if node.owner_key:
            self.members[node.owner_key].append(node)
        if node.kind is NodeKind.FUNCTION and node.name != "constructor":
            self.functions_by_name[node.name].append(node)
        if node.kind in _SYMBOL_KINDS and "." not in node.qualname and " > " not in node.qualname:
            info.top.setdefault(node.qualname.partition("#")[0], node)
            if node.attrs.get("default_export") and info.default is None:
                info.default = node

    def method(self, class_key: str, name: str) -> Node | None:
        for member in self.members.get(class_key, ()):
            if member.name == name and member.kind is NodeKind.FUNCTION:
                return member
        return None


class Exports:
    """What each file exports, following `export ... from` for at most five hops."""

    def __init__(self, tables: Tables, modules: ModuleResolver) -> None:
        self._tables = tables
        self._modules = modules

    def lookup(self, path: str, name: str) -> Found | None:
        return self._lookup(path, name, 0, set())

    def _lookup(self, path: str, name: str, hops: int, seen: set[tuple[str, str]]) -> Found | None:
        info = self._tables.files.get(path)
        if info is None or hops > MAX_HOPS or (path, name) in seen:
            return None
        seen.add((path, name))
        own = info.top.get(name) or (info.default if name == "default" else None)
        if own is not None:
            return Found(own.key)
        for reexport in (i for i in info.imports if i.is_reexport):
            target = self._modules.resolve(reexport.target, path).path
            if target is None:
                continue
            found = self._through(reexport, target, name, hops, seen)
            if found is not None:
                return found
        return None

    def _through(
        self, reexport: RawImport, target: str, name: str, hops: int, seen: set[tuple[str, str]]
    ) -> Found | None:
        for original, alias in reexport.names:
            if (alias or original) == name:
                return self._lookup(target, original, hops + 1, seen)
        if not reexport.names and reexport.alias == name:
            return Found(f"{target}::", is_module=True)  # export * as name from
        if not reexport.names and reexport.alias is None and name != "default":
            return self._lookup(target, name, hops + 1, seen)  # export * from
        return None

    def symbols(self, path: str) -> dict[str, Found]:
        """Every name `path` exports that leads to a symbol (for `export *` and barrels)."""
        return self._symbols(path, 0, set())

    def _symbols(self, path: str, hops: int, seen: set[str]) -> dict[str, Found]:
        info = self._tables.files.get(path)
        if info is None or hops > MAX_HOPS or path in seen:
            return {}
        seen.add(path)
        found = {name: Found(node.key) for name, node in info.top.items()}
        for reexport in (i for i in info.imports if i.is_reexport):
            target = self._modules.resolve(reexport.target, path).path
            if target is None:
                continue
            if reexport.names:
                for original, alias in reexport.names:
                    hit = self._lookup(target, original, hops + 1, set())
                    if hit is not None:
                        found.setdefault(alias or original, hit)
            elif reexport.alias is None:
                for name, hit in self._symbols(target, hops + 1, seen).items():
                    if name != "default":
                        found.setdefault(name, hit)
        return found
