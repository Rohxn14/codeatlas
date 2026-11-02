"""Resolve a written name (`Base`, `ns.Base<T>`, `UserApi`) in one file to a symbol."""

from __future__ import annotations

from dataclasses import dataclass

from codeatlas.indexer.languages.typescript.resolver.bindings import (
    EXTERNAL_PREFIX,
    FileContext,
)
from codeatlas.indexer.languages.typescript.resolver.tables import Exports, Tables
from codeatlas.models import Node


@dataclass(frozen=True, slots=True)
class Named:
    """A name's meaning: a repository `node`, or an `external` name (without the prefix)."""

    node: Node | None = None
    external: str | None = None


class NameResolver:
    def __init__(self, tables: Tables, exports: Exports, contexts: dict[str, FileContext]) -> None:
        self._tables = tables
        self._exports = exports
        self._contexts = contexts

    def resolve(self, text: str, path: str) -> Named | None:
        """The class, interface or function `text` names inside file `path`."""
        ctx = self._contexts.get(path)
        if ctx is None:
            return None
        parts = text.partition("<")[0].strip().replace("?.", ".").split(".")
        if not parts or not parts[0]:
            return None
        head, rest = parts[0], parts[1:]
        local = ctx.info.top.get(head)
        if local is not None:
            return Named(node=local) if not rest else None
        binding = ctx.bindings.get(head)
        if binding is None:
            return None
        if binding.kind == "external":
            return Named(external=_external_name(binding.target, binding.name, rest))
        if binding.kind == "symbol":
            return Named(node=self._tables.nodes.get(binding.target)) if not rest else None
        if binding.kind == "namespace" and len(rest) == 1:
            found = self._exports.lookup(binding.target, rest[0])
            node = self._tables.nodes.get(found.key) if found and not found.is_module else None
            return Named(node=node) if node else None
        return None


def _external_name(specifier: str, imported: str | None, rest: list[str]) -> str:
    """`import {Component} from "react"` -> `react.Component`; `React.Component` too."""
    tail = rest or ([imported] if imported and imported != "default" else [])
    return ".".join([specifier, *tail])


def external_key(name: str) -> str:
    return EXTERNAL_PREFIX + name
