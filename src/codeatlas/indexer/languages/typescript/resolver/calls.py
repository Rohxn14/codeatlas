"""The four call-resolution levels (contract section 5) for one raw call."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from codeatlas.indexer.languages.typescript.resolver.bindings import FileContext
from codeatlas.indexer.languages.typescript.resolver.names import Named, NameResolver, external_key
from codeatlas.indexer.languages.typescript.resolver.tables import Exports, Tables
from codeatlas.models import Node, NodeKind, RawCall, Resolution

MAX_CANDIDATES = 5  # above this a same-name match says nothing (plan, decision 2)
GUESS_CAP = 0.3
SELF_METHOD_CONFIDENCE = 0.9
MAX_BASE_DEPTH = 6

GLOBALS = frozenset(
    ["console", "JSON", "Math", "Object", "Array", "Promise", "Date", "Number", "String", "Boolean", "Symbol", "Map", "Set", "WeakMap", "WeakSet", "Error", "RegExp", "Reflect", "Intl", "BigInt", "Buffer", "process", "window", "document", "navigator", "location", "localStorage", "sessionStorage", "globalThis", "setTimeout", "setInterval", "clearTimeout", "clearInterval", "setImmediate", "queueMicrotask", "structuredClone", "fetch", "parseInt", "parseFloat", "isNaN", "isFinite", "encodeURIComponent", "decodeURIComponent", "encodeURI", "decodeURI", "atob", "btoa", "alert", "URL", "URLSearchParams", "AbortController", "TextEncoder", "TextDecoder", "requestAnimationFrame", "describe", "it", "test", "expect", "beforeEach", "afterEach", "beforeAll", "afterAll", "jest", "vi", "require"]
)
_CHAIN = re.compile(r"^[A-Za-z_$][\w$]*(?:\??\.[A-Za-z_$#][\w$]*)*$")


@dataclass(frozen=True, slots=True)
class Hit:
    """One candidate answer for a call."""

    dst_key: str
    resolution: Resolution
    confidence: float
    attrs: dict[str, object] = field(default_factory=dict)


class CallResolver:
    def __init__(
        self,
        tables: Tables,
        exports: Exports,
        names: NameResolver,
        contexts: dict[str, FileContext],
    ) -> None:
        self._t = tables
        self._exports = exports
        self._names = names
        self._contexts = contexts

    def resolve(self, call: RawCall, caller: Node) -> list[Hit]:
        ctx = self._contexts.get(caller.path)
        if ctx is None:
            return []
        for attempt in (self._direct, self._self_method):
            hits = attempt(call, caller, ctx)
            if hits is not None:
                return hits
        return self._scoped(call, ctx) or self._guess(call)

    # --- DIRECT -----------------------------------------------------------------------

    def _direct(self, call: RawCall, caller: Node, ctx: FileContext) -> list[Hit] | None:
        """None means "not decided here"; an empty list means "decided: no edge"."""
        if call.receiver is None:
            return self._bare(call, caller, ctx)
        if call.receiver in ("this", "super") or not _CHAIN.match(call.receiver):
            return None
        segments = call.receiver.replace("?.", ".").split(".")
        binding = ctx.bindings.get(segments[0])
        local = ctx.info.top.get(segments[0])
        if binding is None and local is None:
            return _global(call) if segments[0] in GLOBALS else None
        if local is not None and binding is None:
            return self._static(local, segments[1:], call.name)
        assert binding is not None
        if binding.kind == "external":
            return [Hit(external_key(f"{binding.target}.{call.name}"), Resolution.DIRECT, 1.0)]
        if binding.kind == "namespace":
            return self._through_namespace(binding.target, segments[1:], call.name)
        if binding.kind == "symbol":
            node = self._t.nodes.get(binding.target)
            return self._static(node, segments[1:], call.name) if node else None
        return None

    def _bare(self, call: RawCall, caller: Node, ctx: FileContext) -> list[Hit] | None:
        nested = self._nested(caller, call.name)
        target = nested or ctx.info.top.get(call.name)
        if target is not None:
            return self._to_symbol(target)
        binding = ctx.bindings.get(call.name)
        if binding is None:
            return _global(call) if call.name in GLOBALS else None
        if binding.kind == "external":
            name = binding.target if binding.name in (None, "default") else (
                f"{binding.target}.{binding.name}"
            )
            return [Hit(external_key(name), Resolution.DIRECT, 1.0)]
        if binding.kind == "symbol":
            node = self._t.nodes.get(binding.target)
            return self._to_symbol(node) if node else []
        return []  # a variable or a namespace called as a function: nothing to point at

    def _nested(self, caller: Node, name: str) -> Node | None:
        """A function defined inside the caller or beside it: `outer.inner` called as `inner()`."""
        parts = caller.qualname.partition("#")[0].split(".")
        for size in range(len(parts), 0, -1):
            node = self._t.nodes.get(f"{caller.path}::{'.'.join(parts[:size])}.{name}")
            if node is not None and node.owner_key is None and node.kind is NodeKind.FUNCTION:
                return node
        return None

    def _to_symbol(self, node: Node) -> list[Hit]:
        """A function is the callee; a class means its written constructor, or no edge."""
        if node.kind is NodeKind.FUNCTION:
            return [Hit(node.key, Resolution.DIRECT, 1.0)]
        if node.kind is NodeKind.CLASS:
            ctor = self._t.method(node.key, "constructor")
            return [Hit(ctor.key, Resolution.DIRECT, 1.0)] if ctor else []
        return []

    def _static(self, node: Node, rest: list[str], name: str) -> list[Hit] | None:
        """`UserApi.create()`: a method found on the class or its bases."""
        if rest or node.kind is not NodeKind.CLASS:
            return None
        method = self._find_method(node, name, set(), 0)
        return [Hit(method.key, Resolution.DIRECT, 1.0)] if method else None

    def _through_namespace(self, path: str, rest: list[str], name: str) -> list[Hit]:
        """`ns.f()` and `ns.Class.m()` where `ns` is `import * as ns` or `require`."""
        if not rest:
            found = self._exports.lookup(path, name)
            node = self._t.nodes.get(found.key) if found and not found.is_module else None
            return self._to_symbol(node) if node else []
        found = self._exports.lookup(path, rest[0])
        node = self._t.nodes.get(found.key) if found and not found.is_module else None
        return (self._static(node, rest[1:], name) or []) if node else []

    # --- SELF_METHOD ------------------------------------------------------------------

    def _self_method(self, call: RawCall, caller: Node, ctx: FileContext) -> list[Hit] | None:
        if call.receiver not in ("this", "super"):
            return None
        cls = self._enclosing_class(caller)
        if cls is None:
            return None
        start = cls
        if call.receiver == "super":
            method = self._find_in_bases(cls, call.name, set(), 0)
        else:
            method = self._find_method(start, call.name, set(), 0)
        if method is None:
            return None
        return [Hit(method.key, Resolution.SELF_METHOD, SELF_METHOD_CONFIDENCE)]

    def _enclosing_class(self, caller: Node) -> Node | None:
        if caller.owner_key:
            return self._t.nodes.get(caller.owner_key)
        parts = caller.qualname.partition("#")[0].split(".")
        for size in range(len(parts) - 1, 0, -1):
            node = self._t.nodes.get(f"{caller.path}::{'.'.join(parts[:size])}")
            if node is not None and node.kind is NodeKind.CLASS:
                return node
        return None

    def _find_method(self, cls: Node, name: str, seen: set[str], depth: int) -> Node | None:
        if cls.key in seen or depth > MAX_BASE_DEPTH:
            return None
        seen.add(cls.key)
        return self._t.method(cls.key, name) or self._find_in_bases(cls, name, seen, depth)

    def _find_in_bases(self, cls: Node, name: str, seen: set[str], depth: int) -> Node | None:
        for base in self.bases(cls):
            if base.node is not None and base.node.kind is NodeKind.CLASS:
                found = self._find_method(base.node, name, seen, depth + 1)
                if found:
                    return found
        return None

    def bases(self, cls: Node) -> list[Named]:
        """The `extends`/`implements` names of a class, resolved through its file's imports."""
        written = cls.attrs.get("bases")
        resolved: list[Named] = []
        for text in written if isinstance(written, list) else []:
            found = self._names.resolve(str(text), cls.path)
            if found is not None:
                resolved.append(found)
        return resolved

    # --- IMPORT_SCOPED and NAME_GUESS -------------------------------------------------

    def _scoped(self, call: RawCall, ctx: FileContext) -> list[Hit]:
        files = ctx.imported_files | {ctx.info.path}
        found = [n for n in self._t.functions_by_name.get(call.name, ()) if n.path in files]
        if not found or len(found) > MAX_CANDIDATES:
            return []
        return [
            Hit(n.key, Resolution.IMPORT_SCOPED, 1 / len(found), {"candidates": len(found)})
            for n in found
        ]

    def _guess(self, call: RawCall) -> list[Hit]:
        found = self._t.functions_by_name.get(call.name, ())
        if not found or len(found) > MAX_CANDIDATES:
            return []
        confidence = min(GUESS_CAP, 1 / len(found))
        return [
            Hit(n.key, Resolution.NAME_GUESS, confidence, {"candidates": len(found)}) for n in found
        ]


def _global(call: RawCall) -> list[Hit]:
    return [Hit(external_key(f"globals.{call.callee_text.replace('?.', '.')}"), Resolution.DIRECT, 1.0)]
