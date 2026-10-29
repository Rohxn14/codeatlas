"""Interfaces between indexing stages (docs/contract.md, section 7)."""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from codeatlas.models import Edge, FileRecord, Node, ParseResult, Tier


@runtime_checkable
class LanguageAdapter(Protocol):
    """Turns one file into a ParseResult."""

    language: str
    tier: Tier
    extensions: tuple[str, ...]

    def parse(self, path: str, source: bytes, snapshot_id: str) -> ParseResult:
        """Pure: no file or network access; never raises on bad syntax."""


@runtime_checkable
class SymbolIndex(Protocol):
    """Read-only lookups resolvers and linkers need; the store implements it."""

    def by_key(self, key: str) -> Node | None: ...

    def by_name(self, name: str, language: str | None = None) -> list[Node]: ...

    def module_for_path(self, path: str) -> Node | None: ...

    def members(self, class_key: str) -> list[Node]: ...

    def files(self) -> list[FileRecord]: ...


@runtime_checkable
class RepoAnalyzer(Protocol):
    """Whole-repository analysis that needs no parser (the repository layer)."""

    name: str

    def analyze(
        self, repo_root: Path, files: Sequence[FileRecord], snapshot_id: str
    ) -> tuple[list[Node], list[Edge]]:
        """May read files and run read-only git commands.

        Never runs build tools, package managers or repository code.
        """


@runtime_checkable
class Resolver(Protocol):
    """Turns one language family's raw items into edges."""

    languages: frozenset[str]

    def resolve(self, results: Sequence[ParseResult], index: SymbolIndex) -> list[Edge]:
        """Produces IMPORTS, CALLS, INHERITS and TESTS edges for its languages.

        CONTAINS edges come from the pipeline, for every tier.
        """


@runtime_checkable
class Linker(Protocol):
    """Connects things across files and languages."""

    name: str

    def link(
        self, results: Sequence[ParseResult], index: SymbolIndex, snapshot_id: str
    ) -> tuple[list[Node], list[Edge]]:
        """May create nodes (ROUTE) and edges (HANDLES, CALLS_HTTP)."""
