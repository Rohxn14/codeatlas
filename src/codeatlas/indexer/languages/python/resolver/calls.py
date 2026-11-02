"""CALLS: decide what each raw call runs, by the table in the T06 brief.

Tried in this order, the first that answers wins:

1. the name is bound: a nested function, a definition, an import, a builtin (DIRECT);
2. `self.m()`, `cls.m()`, `super().m()`, or a receiver whose class is declared
   (SELF_METHOD, 0.9: the method is found through the class's bases, but a subclass could
   override it);
3. the receiver's type is unknown: the name in the caller's file and the files it
   imports (IMPORT_SCOPED, 1 / candidates);
4. the name anywhere in the repository (NAME_GUESS, 1 / candidates, at most 0.3).

A call that none of these settles stays a raw call. That is deliberate for `getattr(..)()`,
`HANDLERS[name](..)` and calling a parameter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from codeatlas.indexer.languages.python.resolver.names import Names, Ref
from codeatlas.indexer.languages.python.resolver.tables import ModuleTable
from codeatlas.indexer.languages.python.resolver.types import Typer
from codeatlas.models import Node, NodeKind, RawCall, Resolution

EXTERNAL_PREFIX = "::external:"
TYPED_CONFIDENCE = 0.9
GUESS_CAP = 0.3
MAX_GUESS_CANDIDATES = 5  # decision 3 in docs/plans/T06.md
# Method names of builtin containers and strings. A repository method with one of these
# names is almost never what `x.get()` means, so a blind guess is not made for them.
NO_GUESS = frozenset({
    "get", "set", "add", "pop", "push", "append", "extend", "insert", "remove", "clear",
    "copy", "update", "items", "keys", "values", "join", "split", "strip", "format",
    "replace", "startswith", "endswith", "lower", "upper", "encode", "decode", "read",
    "write", "close", "open", "count", "index", "sort", "find",
})
_CALL_RECEIVER = re.compile(r"^([A-Za-z_][\w.]*)\(.*\)$")
_DOTTED = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$")


@dataclass(frozen=True, slots=True)
class Target:
    """One answer for a call: a node key (or an external key), how, and how sure."""

    key: str
    resolution: Resolution
    confidence: float
    candidates: int = 1


def direct(key: str, share: int = 1) -> Target:
    return Target(key, Resolution.DIRECT, 1.0 / share, share)


class CallResolver:
    def __init__(self, names: Names, typer: Typer, tables: dict[str, ModuleTable]) -> None:
        self.names = names
        self.typer = typer
        self.tables = tables
        self.methods: dict[str, list[Node]] = {}
        self.functions: dict[str, list[Node]] = {}
        for table in tables.values():
            self._add_pools(table)
        self._scope: dict[str, frozenset[str]] = {}

    def _add_pools(self, table: ModuleTable) -> None:
        """Name -> definitions. Overloads of one method count as a single candidate.

        Three `@overload` stubs and the implementation are one method to a caller; counting
        them as four would split the confidence and guess at the stubs.
        """
        last: dict[tuple[str, str, str], Node] = {}
        for node in table.by_qualname.values():
            if node.kind is NodeKind.FUNCTION:
                parent = node.qualname.rpartition(".")[0]
                last[(node.name, parent, "m" if node.owner_key else "f")] = node
        for (name, parent, kind), node in last.items():
            if kind == "m":
                self.methods.setdefault(name, []).append(node)
            elif not parent:
                self.functions.setdefault(name, []).append(node)

    def resolve(self, call: RawCall, caller: Node) -> list[Target]:
        """Targets for one call made inside `caller` (empty means: leave it raw)."""
        if not call.name.isidentifier():
            return []
        table = self.tables[caller.path]
        params = self._params(table, caller)
        if call.receiver is None:
            if call.callee_text != call.name or call.name in params:
                return []
            return self._bare(call, caller, table)
        return self._with_receiver(call, caller, table, params)

    # --- calls without a receiver ----------------------------------------------

    def _bare(self, call: RawCall, caller: Node, table: ModuleTable) -> list[Target]:
        local = self._nested(table, caller, call.name)
        if local is not None:
            return [direct(local.key)]
        ref = self.names.ref(table.path, call.name)
        if ref is not None:
            return self._targets(ref)
        return self._scoped(call, caller, table, self.functions, guess=True)

    def _nested(self, table: ModuleTable, caller: Node, name: str) -> Node | None:
        qualname = caller.qualname
        while qualname:
            found = table.nested.get(qualname, {}).get(name)
            if found is not None and found.kind in (NodeKind.FUNCTION, NodeKind.TEST):
                return found
            qualname = qualname.rpartition(".")[0]
        return None

    def _targets(self, ref: Ref) -> list[Target]:
        """DIRECT targets for a name that resolved; a class means its `__init__`."""
        if ref.kind == "external":
            return [direct(EXTERNAL_PREFIX + ref.name)]
        if ref.kind != "node":
            return []
        found: list[Node] = []
        for node in ref.nodes:
            if node.kind is NodeKind.CLASS:
                node = self.names.find_member(node, "__init__")  # type: ignore[assignment]
            if node is not None:
                found.append(node)
        return [direct(n.key, len(found)) for n in found]

    # --- calls with a receiver -------------------------------------------------

    def _with_receiver(
        self, call: RawCall, caller: Node, table: ModuleTable, params: dict[str, str | None]
    ) -> list[Target]:
        receiver = call.receiver or ""
        if receiver in ("self", "cls"):
            return self._method(self._class_of(table, caller), call.name)
        if receiver == "super()":
            return self._method(self._class_of(table, caller), call.name, skip_self=True)
        if _DOTTED.match(receiver) and receiver.split(".")[0] not in params:
            ref = self.names.ref(table.path, call.callee_text)
            if ref is not None:  # module.func, Class.method, os.path.join
                return self._targets(ref)
        cls = self._receiver_class(receiver, caller, table, params)
        if cls is not None:
            return self._method(cls, call.name)
        return self._scoped(call, caller, table, self.methods, guess=call.name not in NO_GUESS)

    def _method(self, cls: Node | None, name: str, skip_self: bool = False) -> list[Target]:
        member = self.names.find_member(cls, name, skip_self) if cls is not None else None
        if member is None:
            return []
        return [Target(member.key, Resolution.SELF_METHOD, TYPED_CONFIDENCE)]

    def _receiver_class(
        self, receiver: str, caller: Node, table: ModuleTable, params: dict[str, str | None]
    ) -> Node | None:
        """The class a receiver is declared to be, or None (decision 1 and 2 in the plan)."""
        head, _, attr = receiver.partition(".")
        if head in ("self", "cls") and attr and "." not in attr:
            cls = self._class_of(table, caller)
            return self.typer.attribute_class(cls, attr) if cls is not None else None
        if receiver in params:
            return self.typer.annotated_class(table.path, params[receiver])
        built = _CALL_RECEIVER.match(receiver)
        ref = self.names.ref(table.path, built.group(1)) if built else None
        if ref is None or ref.kind != "node":
            return None
        node = ref.nodes[0]
        return node if node.kind is NodeKind.CLASS else self.typer.return_class(node)

    def _class_of(self, table: ModuleTable, caller: Node) -> Node | None:
        """The class whose `self` this code sees: the caller's, or the method around it."""
        node: Node | None = caller
        while node is not None:
            if node.owner_key:
                return self.names.class_nodes.get(node.owner_key)
            parent = node.qualname.rpartition(".")[0]
            node = table.by_qualname.get(parent) if parent else None
        return None

    # --- unknown receivers -----------------------------------------------------

    def _scoped(
        self, call: RawCall, caller: Node, table: ModuleTable, pool: dict[str, list[Node]],
        guess: bool,
    ) -> list[Target]:
        """IMPORT_SCOPED within the files in reach, else NAME_GUESS repository-wide.

        The caller itself is never a candidate: `self.items.get()` inside `Repo.get` is
        a dictionary call, not recursion.
        """
        options = [n for n in pool.get(call.name, []) if n.key != caller.key]
        near = [n for n in options if n.path in self._reach(table)]
        if near:
            return [Target(n.key, Resolution.IMPORT_SCOPED, 1 / len(near), len(near)) for n in near]
        if guess and 0 < len(options) <= MAX_GUESS_CANDIDATES:
            confidence = min(GUESS_CAP, 1 / len(options))
            return [Target(n.key, Resolution.NAME_GUESS, confidence, len(options)) for n in options]
        return []

    def _reach(self, table: ModuleTable) -> frozenset[str]:
        """The caller's file and the files it imports from, including re-export origins."""
        cached = self._scope.get(table.path)
        if cached is None:
            paths = {table.path}
            for binding in [*table.bindings.values(), *table.star_imports]:
                paths.update(binding.paths)
                ref = self.names.follow(binding, 3) if binding.name else None
                if ref is not None and ref.kind == "node":
                    paths.update(n.path for n in ref.nodes)
            cached = self._scope[table.path] = frozenset(paths)
        return cached

    def _params(self, table: ModuleTable, caller: Node) -> dict[str, str | None]:
        """Parameters visible in `caller`: its own and those of the functions around it."""
        params: dict[str, str | None] = {}
        node: Node | None = caller
        while node is not None:
            if node.kind in (NodeKind.FUNCTION, NodeKind.TEST):
                for name, annotation in self.typer.signature(node).params.items():
                    params.setdefault(name, annotation)
            parent = node.qualname.rpartition(".")[0]
            node = table.by_qualname.get(parent) if parent else None
        return params
