"""Name lookup: what a dotted text means in a file, class hierarchies, builtins.

`Names.ref` walks a text such as `os.path.join`, `BaseRepo` or `UserRepo.save` one part
at a time, starting from a local definition, an import or a builtin, and returns a `Ref`:
repository symbols, repository modules, or a name outside the repository.
"""

from __future__ import annotations

import builtins
import re
from dataclasses import dataclass

from codeatlas.indexer.languages.python.resolver.project import Project
from codeatlas.indexer.languages.python.resolver.tables import Binding, ModuleTable
from codeatlas.models import Node, NodeKind

BUILTIN_NAMES = frozenset(n for n in dir(builtins) if not n.startswith("_"))
MAX_REEXPORT_HOPS = 3
MAX_MRO_DEPTH = 10
_DOTTED = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$")


@dataclass(frozen=True, slots=True)
class Ref:
    """What a name points at: `node` (symbols), `module` (files) or `external`."""

    kind: str
    nodes: tuple[Node, ...] = ()
    paths: tuple[str, ...] = ()
    name: str = ""


def external(name: str) -> Ref:
    return Ref("external", name=name)


@dataclass(slots=True)
class Mro:
    """A class and the classes it inherits from, nearest first.

    `complete` is False when some base could not be found in the repository (a library
    class, a dynamic base): a method missing from `classes` may live there.
    """

    classes: list[Node]
    complete: bool


class Names:
    def __init__(self, tables: dict[str, ModuleTable], project: Project) -> None:
        self.tables = tables
        self.project = project
        self.class_nodes: dict[str, Node] = {
            n.key: n for t in tables.values() for n in t.by_qualname.values()
            if n.kind is NodeKind.CLASS
        }
        self.members_of: dict[str, dict[str, Node]] = {}
        for table in tables.values():
            for node in table.by_qualname.values():
                if node.owner_key:
                    self.members_of.setdefault(node.owner_key, {})[node.name] = node
        self._mro: dict[str, Mro] = {}

    # --- names -----------------------------------------------------------------

    def ref(self, path: str, text: str) -> Ref | None:
        """Resolve a dotted text as seen from module `path`; None when unknown."""
        if not _DOTTED.match(text) or path not in self.tables:
            return None
        parts = text.split(".")
        start = self._start(self.tables[path], parts)
        if start is None:
            return None
        current, used = start
        for part in parts[used:]:
            current = self._step(current, part)
            if current is None:
                return None
        return current

    def _start(self, table: ModuleTable, parts: list[str]) -> tuple[Ref, int] | None:
        if parts[0] in table.defs:
            return Ref("node", (table.defs[parts[0]],)), 1
        for used in range(len(parts), 0, -1):  # longest import prefix: `a.b` before `a`
            binding = table.bindings.get(".".join(parts[:used]))
            if binding is not None:
                resolved = self.follow(binding, MAX_REEXPORT_HOPS)
                return (resolved, used) if resolved is not None else None
        for star in table.star_imports:
            resolved = self.follow(Binding(star.paths, star.external, parts[0]), MAX_REEXPORT_HOPS)
            if resolved is not None:
                return resolved, 1
        if parts[0] in BUILTIN_NAMES:
            return external(f"builtins.{parts[0]}"), 1
        return None

    def _step(self, current: Ref, part: str) -> Ref | None:
        if current.kind == "external":
            return external(f"{current.name}.{part}")
        if current.kind == "module":
            for path in current.paths:
                found = self.export(path, part, MAX_REEXPORT_HOPS)
                if found is not None:
                    return found
            return None
        node = current.nodes[0]
        if node.kind is not NodeKind.CLASS:
            return None
        member = self.find_member(node, part)
        return Ref("node", (member,)) if member is not None else None

    def follow(self, binding: Binding, hops: int) -> Ref | None:
        """Turn an import binding into what it names, following re-exports."""
        if binding.name is None:
            if binding.paths:
                return Ref("module", paths=binding.paths)
            return external(binding.external) if binding.external else None
        if not binding.paths:
            return external(f"{binding.external}.{binding.name}") if binding.external else None
        found: list[Ref] = []
        for path in binding.paths:
            ref = self.export(path, binding.name, hops)
            if ref is not None:
                found.append(ref)
        return _merge(found)

    def export(self, path: str, name: str, hops: int) -> Ref | None:
        """What `from <path> import name` gives: a definition, a re-export or a submodule."""
        table = self.tables.get(path)
        if table is None:
            return None
        if name in table.defs:
            return Ref("node", (table.defs[name],))
        if hops > 0:
            binding = table.bindings.get(name)
            if binding is not None:
                ref = self.follow(binding, hops - 1)
                if ref is not None:
                    return ref
            for star in table.star_imports:
                ref = self.follow(Binding(star.paths, star.external, name), hops - 1)
                if ref is not None:
                    return ref
        sub = self.project.child_module(path, name)
        return Ref("module", paths=tuple(sub)) if sub else None

    # --- classes ---------------------------------------------------------------

    def mro(self, cls: Node) -> Mro:
        """Depth-first, left-to-right, each class once, at most MAX_MRO_DEPTH deep."""
        cached = self._mro.get(cls.key)
        if cached is None:
            result = Mro([], True)
            self._visit(cls, result, set(), 0)
            cached = self._mro[cls.key] = result
        return cached

    def _visit(self, cls: Node, out: Mro, seen: set[str], depth: int) -> None:
        if cls.key in seen:
            return
        seen.add(cls.key)
        out.classes.append(cls)
        if depth >= MAX_MRO_DEPTH:
            out.complete = False
            return
        for base in self.bases(cls):
            if base is None:
                out.complete = False
            else:
                self._visit(base, out, seen, depth + 1)

    def bases(self, cls: Node) -> list[Node | None]:
        """Each written base as a repository class, or None when it is not one."""
        found: list[Node | None] = []
        for text in base_names(cls):
            ref = self.ref(cls.path, text) if text else None
            node = ref.nodes[0] if ref and ref.kind == "node" else None
            found.append(node if node is not None and node.kind is NodeKind.CLASS else None)
        return found

    def find_member(self, cls: Node, name: str, skip_self: bool = False) -> Node | None:
        mro = self.mro(cls)
        for klass in mro.classes[1:] if skip_self else mro.classes:
            member = self.members_of.get(klass.key, {}).get(name)
            if member is not None:
                return member
        return None


def base_names(cls: Node) -> list[str]:
    """Bases as dotted names: `Generic[T]` becomes `Generic`; odd forms become ''."""
    names = []
    for raw in cls.attrs.get("bases", []) or []:
        text = str(raw).split("[", 1)[0].strip()
        if "=" in text:  # a keyword such as metaclass=ABCMeta is not a base
            continue
        names.append(text if _DOTTED.match(text) else "")
    return names


def _merge(refs: list[Ref]) -> Ref | None:
    """One ref from several candidate files: keep the first kind found, join its items."""
    if not refs:
        return None
    first = refs[0]
    same = [r for r in refs if r.kind == first.kind]
    if first.kind == "node":
        seen: dict[str, Node] = {}
        for ref in same:
            for node in ref.nodes:
                seen.setdefault(node.key, node)
        return Ref("node", tuple(seen.values()))
    if first.kind == "module":
        paths = tuple(dict.fromkeys(p for r in same for p in r.paths))
        return Ref("module", paths=paths)
    return first
