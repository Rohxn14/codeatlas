"""The structural resolver: import-scoped CALLS and IMPORTS for any tree-sitter language.

Shared by every language: this file never mentions Java or Go. A language contributes a
`Profile` (what an import reaches, what a package contains); languages without one still
get name guesses, so each has some CALLS edges.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from codeatlas.indexer.adapter import SymbolIndex
from codeatlas.indexer.registry import GRAMMARS
from codeatlas.indexer.structural.context import Context, FileInfo
from codeatlas.indexer.structural.go import GoProfile
from codeatlas.indexer.structural.java import JavaProfile
from codeatlas.indexer.structural.profile import Profile, Reach
from codeatlas.models import (
    DEEP_LANGUAGES,
    Edge,
    EdgeKind,
    Node,
    ParseResult,
    RawCall,
    Resolution,
    make_node_id,
)

MAX_GUESSES = 5  # a name defined more than this often is too common to guess at
MAX_GUESS_CONFIDENCE = 0.3
MAX_IMPORT_FILES = 10  # IMPORTS edges for a package nobody calls into
_SELF_RECEIVERS = frozenset({"this", "self", "super"})

PROFILES: tuple[Profile, ...] = (JavaProfile(), GoProfile())
_PROFILE_BY_LANGUAGE: dict[str, Profile] = {
    language: profile for profile in PROFILES for language in profile.languages
}


@dataclass(slots=True)
class _FileState:
    """Per-file working data: what each import reaches and which files calls landed in."""

    reaches: list[Reach]
    bindings: dict[str, Reach]
    used: list[set[str]] = field(default_factory=list)


class StructuralResolver:
    """Resolver for every structural-tier language in the registry."""

    languages: frozenset[str] = frozenset(GRAMMARS) - DEEP_LANGUAGES

    def resolve(self, results: Sequence[ParseResult], index: SymbolIndex) -> list[Edge]:
        ctx = Context.build(list(results), index)
        calls_of = {r.path: r.calls for r in results}
        edges: list[Edge] = []
        for info in ctx.files.values():
            profile = _PROFILE_BY_LANGUAGE.get(info.language)
            state = _file_state(ctx, info, profile)
            calls = calls_of.get(info.path, ())
            for call in calls:
                edges += _resolve_call(ctx, info, profile, state, call)
            edges += _import_edges(ctx, info, state)
        return edges


def _file_state(ctx: Context, info: FileInfo, profile: Profile | None) -> _FileState:
    if profile is None:
        return _FileState([], {})
    reaches = [profile.reach(ctx, info, imp) for imp in info.imports]
    bindings = {r.binding: r for r in reaches if r.binding}
    return _FileState(reaches, bindings, [set() for _ in reaches])


# Calls


def _resolve_call(
    ctx: Context, info: FileInfo, profile: Profile | None, state: _FileState, call: RawCall
) -> list[Edge]:
    source = make_node_id(info.module.snapshot_id, call.caller_key)
    if profile is not None:
        reach = state.bindings.get(call.receiver or "")
        if reach is not None:
            found = _through_import(ctx, state, reach, call)
            if found is not None:
                return _call_edges(source, found, call, Resolution.IMPORT_SCOPED)
        else:
            scoped = _in_scope(ctx, info, profile, state, call)
            if scoped:
                return _call_edges(source, scoped, call, Resolution.IMPORT_SCOPED)
    return _call_edges(source, _guess(ctx, info, call), call, Resolution.NAME_GUESS)


@dataclass(frozen=True, slots=True)
class _Targets:
    """Where a call may land: repository functions, or one external name."""

    nodes: tuple[Node, ...] = ()
    external: str | None = None

    def __bool__(self) -> bool:
        return bool(self.nodes or self.external)


def _through_import(
    ctx: Context, state: _FileState, reach: Reach, call: RawCall
) -> _Targets | None:
    """`pkg.F()` / `C.m()`: the qualifier is an import, so look only where it points."""
    if reach.external is not None:
        return _Targets(external=f"{reach.external}.{call.name}")
    nodes = _members(ctx, reach, call.name)
    if nodes:
        _mark_used(state, reach, nodes)
        return _Targets(tuple(nodes))
    return None  # the import is internal but the name is not there: fall back to a guess


def _in_scope(
    ctx: Context, info: FileInfo, profile: Profile, state: _FileState, call: RawCall
) -> _Targets | None:
    """Nearest scope with a definition wins: class chain, own file, package, imports."""
    name, receiver = call.name, call.receiver
    unqualified = receiver is None
    if (unqualified or receiver in _SELF_RECEIVERS) and profile.has_class_chain:
        chain = _class_chain(ctx, info, call.caller_key, name)
        if chain:
            return _Targets(tuple(chain))
        if receiver in _SELF_RECEIVERS:
            return None
    tiers = [[info.path]]
    if not unqualified or profile.unqualified_uses_package:
        tiers.append(profile.package_scope(ctx, info))
    for paths in tiers:
        nodes = _functions_in(ctx, paths, name, profile.unqualified_is_toplevel and unqualified)
        if nodes:
            return _Targets(tuple(nodes))
    return _from_imports(ctx, state, call)


def _from_imports(ctx: Context, state: _FileState, call: RawCall) -> _Targets | None:
    nodes: list[Node] = []
    for reach in state.reaches:
        if reach.external is not None:
            if call.receiver is None and reach.names and call.name in reach.names:
                return _Targets(external=f"{reach.external}.{call.name}")
            continue
        if call.receiver is None and (reach.names is not None and call.name not in reach.names):
            continue
        found = _members(ctx, reach, call.name, any_owner=call.receiver is not None)
        _mark_used(state, reach, found)
        nodes += found
    if call.receiver is not None and len(nodes) > MAX_GUESSES:
        # An untyped receiver matched many same-named methods (jsoup had calls with 78
        # candidates at 0.013 each). That is a guess, not a scoped answer: give up, as a
        # name guess with this many candidates would.
        return _Targets()
    return _Targets(tuple(nodes)) if nodes else None


def _members(ctx: Context, reach: Reach, name: str, any_owner: bool = False) -> list[Node]:
    """Functions called `name` in the reached files, restricted to a class if the import is.

    `any_owner` drops the restriction: the receiver is a variable of unknown type, so a
    method of any class in the reached files may be the one called.
    """
    found = []
    for path in reach.paths:
        for node in ctx.files[path].functions.get(name, []):
            if any_owner:
                found.append(node)
            elif reach.class_name is None:
                if node.owner_key is None:
                    found.append(node)
            elif _owner_name(node) == reach.class_name:
                found.append(node)
    return found


def _mark_used(state: _FileState, reach: Reach, nodes: Sequence[Node]) -> None:
    for position, candidate in enumerate(state.reaches):
        if candidate is reach:
            state.used[position].update(n.path for n in nodes)


def _functions_in(ctx: Context, paths: Sequence[str], name: str, toplevel: bool) -> list[Node]:
    found = []
    for path in paths:
        for node in ctx.files[path].functions.get(name, []):
            if not toplevel or node.owner_key is None:
                found.append(node)
    return found


def _class_chain(ctx: Context, info: FileInfo, caller_key: str, name: str) -> list[Node]:
    """Methods called `name` in the caller's class, then in the classes around it."""
    caller = info.nodes.get(caller_key)
    owner = info.nodes.get(caller.owner_key or "") if caller else None
    while owner is not None:
        methods = [n for n in info.functions.get(name, []) if n.owner_key == owner.key]
        if methods:
            return methods
        owner = info.nodes.get(owner.owner_key or "") or _enclosing(info, owner)
    return []


def _enclosing(info: FileInfo, node: Node) -> Node | None:
    """The class around a nested class (`Outer` for `Outer.Inner`), if any."""
    if "." not in node.qualname:
        return None
    parent = node.qualname.rsplit(".", 1)[0]
    return next((n for n in info.nodes.values() if n.qualname == parent), None)


def _owner_name(node: Node) -> str | None:
    if node.owner_key is None:
        return None
    return node.owner_key.split("::", 1)[1].rsplit(".", 1)[-1].split("#", 1)[0]


def _guess(ctx: Context, info: FileInfo, call: RawCall) -> _Targets:
    nodes = ctx.functions_by_name.get((info.language, call.name), [])
    return _Targets(tuple(nodes)) if 0 < len(nodes) <= MAX_GUESSES else _Targets()


def _call_edges(
    source: str, targets: _Targets, call: RawCall, resolution: Resolution
) -> list[Edge]:
    """One CALLS edge per candidate, each with 1 / candidates (name guesses capped at 0.3)."""
    snapshot = source.split("/", 1)[0]
    if targets.external:
        destinations = [make_node_id(snapshot, f"::external:{targets.external}")]
    else:
        destinations = [n.id for n in targets.nodes]
    if not destinations:
        return []
    confidence = 1 / len(destinations)
    if resolution is Resolution.NAME_GUESS:
        confidence = min(MAX_GUESS_CONFIDENCE, confidence)
    attrs = {"candidates": len(destinations)} if len(destinations) > 1 else {}
    return [
        Edge(source, dst, EdgeKind.CALLS, confidence, resolution, call.line, dict(attrs))
        for dst in destinations
    ]


# Imports


def _import_edges(ctx: Context, info: FileInfo, state: _FileState) -> list[Edge]:
    """IMPORTS edges: a file, the files that package is used through, or an external.

    An import reaching many files (a Go package, a Java wildcard) points at the files the
    importer calls into; if it calls into none, at the first few by name.
    """
    snapshot = info.module.snapshot_id
    edges = []
    for position, reach in enumerate(state.reaches):
        line = reach.imp.line
        if reach.external is not None:
            dst = make_node_id(snapshot, f"::external:{reach.external}")
            edges.append(Edge(info.module.id, dst, EdgeKind.IMPORTS, 1.0,
                              Resolution.STRUCTURAL, line))
            continue
        paths = _imported_files(reach, state.used[position])
        attrs = {"files_in_package": len(reach.paths)} if len(reach.paths) > 1 else {}
        for path in paths:
            edges.append(Edge(info.module.id, ctx.files[path].module.id, EdgeKind.IMPORTS,
                              1 / len(paths), Resolution.STRUCTURAL, line, dict(attrs)))
    return edges


def _imported_files(reach: Reach, used: set[str]) -> list[str]:
    if len(reach.paths) == 1:
        return list(reach.paths)
    chosen = sorted(used) if used else sorted(reach.paths)[:MAX_IMPORT_FILES]
    return chosen[:MAX_IMPORT_FILES]
