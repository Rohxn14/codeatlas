"""Shared data types: identifiers, enums and data classes (docs/contract.md, sections 3 to 6)."""

from dataclasses import dataclass, field
from enum import StrEnum

# 3. Languages and tiers

DEEP_LANGUAGES: frozenset[str] = frozenset({"python", "typescript", "tsx", "javascript"})


# 4. Identifiers


def make_snapshot_id(repo: str, sha: str) -> str:
    """Id of one indexed commit."""
    return f"{repo}@{sha[:12]}"


def make_key(path: str, qualname: str) -> str:
    """Key of a symbol that survives a new commit, so snapshots can be compared."""
    return f"{path}::{qualname}"


def make_node_id(snapshot_id: str, key: str) -> str:
    """Id of a symbol in one snapshot; unique in the store."""
    return f"{snapshot_id}/{key}"


# 5. Enums


class Tier(StrEnum):
    """How deeply a language is understood."""

    DEEP = "deep"
    STRUCTURAL = "structural"
    TEXT = "text"


class NodeKind(StrEnum):
    """What a node stands for."""

    PACKAGE = "package"
    MODULE = "module"
    CLASS = "class"
    INTERFACE = "interface"
    FUNCTION = "function"
    TEST = "test"
    ROUTE = "route"
    EXTERNAL = "external"
    SECTION = "section"


class EdgeKind(StrEnum):
    """What relationship an edge records."""

    CONTAINS = "contains"
    DEPENDS_ON = "depends_on"
    IMPORTS = "imports"
    CALLS = "calls"
    INHERITS = "inherits"
    TESTS = "tests"
    HANDLES = "handles"
    CALLS_HTTP = "calls_http"
    CO_CHANGES = "co_changes"
    REFERENCES = "references"


class Resolution(StrEnum):
    """How an edge was established; the edge's confidence comes from this."""

    STRUCTURAL = "structural"
    DIRECT = "direct"
    SELF_METHOD = "self_method"
    ROUTE_EXACT = "route_exact"
    ROUTE_PATTERN = "route_pattern"
    IMPORT_SCOPED = "import_scoped"
    NAME_GUESS = "name_guess"
    CONVENTION = "convention"
    HISTORY = "history"


# 6. Data classes


@dataclass(frozen=True, slots=True)
class Span:
    """A source range: lines 1-based and inclusive, columns 0-based."""

    start_line: int
    end_line: int
    start_col: int = 0
    end_col: int = 0


@dataclass(frozen=True, slots=True)
class FileRecord:
    """One file seen by discovery."""

    path: str
    language: str
    tier: Tier
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One indexed commit."""

    id: str
    repo: str
    commit_sha: str
    indexed_at: str
    indexer_version: str
    source: str
    limits_hit: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Node:
    """A package, file or symbol in one snapshot."""

    id: str
    key: str
    snapshot_id: str
    kind: NodeKind
    language: str
    name: str
    qualname: str
    path: str
    span: Span
    signature: str | None = None
    docstring: str | None = None
    owner_key: str | None = None
    attrs: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Edge:
    """A relationship between two nodes, with how it was found and how sure it is."""

    src_id: str
    dst_id: str
    kind: EdgeKind
    confidence: float
    resolution: Resolution
    line: int | None = None
    attrs: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawImport:
    """An import as written; adapters cannot resolve names across files."""

    module_key: str
    target: str
    names: tuple[tuple[str, str | None], ...] = ()
    alias: str | None = None
    level: int = 0
    is_reexport: bool = False
    line: int = 0


@dataclass(frozen=True, slots=True)
class RawCall:
    """A call as written; adapters cannot resolve names across files."""

    caller_key: str
    callee_text: str
    name: str
    receiver: str | None = None
    line: int = 0


@dataclass(frozen=True, slots=True)
class RawRoute:
    """A server endpoint as written."""

    handler_key: str
    method: str
    path_pattern: str
    framework: str
    router: str | None = None
    line: int = 0


@dataclass(frozen=True, slots=True)
class RawHttpCall:
    """A client request as written."""

    caller_key: str
    client: str
    url_text: str
    url_kind: str
    method: str | None = None
    line: int = 0


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Everything an adapter learned from one file."""

    path: str
    language: str
    tier: Tier
    nodes: tuple[Node, ...]
    imports: tuple[RawImport, ...] = ()
    calls: tuple[RawCall, ...] = ()
    routes: tuple[RawRoute, ...] = ()
    http_calls: tuple[RawHttpCall, ...] = ()
    errors: tuple[str, ...] = ()
