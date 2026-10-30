"""Turn SCIP indexes into a reference list keyed like CodeAtlas: who mentions which function.

SCIP records every *occurrence* of a symbol: where it is defined and where it is used.
For ground truth on CALLS edges we want: for each use of a function or method symbol
that sits inside another function's body, the pair (enclosing function, referenced
function) and the line. Three steps:

1. Collect definitions. Each definition occurrence gives the defining file and, from
   the symbol's descriptors, a qualname (`UserService#save().` -> `UserService.save`),
   so its CodeAtlas key is `path::qualname`. Its `enclosing_range` is the body span.
2. Collect scopes per file: the body spans of function definitions, plus, when a
   CodeAtlas node list is given, the spans of its function and test nodes. SCIP knows
   nothing of `it("...")` callbacks, so test cases come only from the node list.
3. For each non-definition occurrence of an in-repo function symbol, the innermost
   scope whose span holds the occurrence's line is the caller.

A reference is not always a call (`expect(x).toBe(UserCard)` mentions `UserCard`
without calling it), so the result is an upper bound for call recall, not exact truth.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from eval.oracle.graph import GraphNode, language_of_path
from eval.oracle.scip import Index

RESOLUTION = "scip"
SCOPE_KINDS = frozenset({"function", "test"})


@dataclass(frozen=True, slots=True)
class Descriptor:
    name: str
    suffix: str  # namespace, type, term, method, parameter, type_parameter, meta, macro


@dataclass(frozen=True, slots=True)
class Definition:
    key: str
    kind: str  # "function" or "class"
    path: str
    start_line: int  # 1-based, inclusive
    end_line: int


@dataclass(frozen=True, slots=True)
class Reference:
    src_key: str
    dst_key: str
    line: int


# Symbols -------------------------------------------------------------------------------


def parse_descriptors(symbol: str) -> list[Descriptor] | None:
    """The descriptors of a global SCIP symbol, or None for a local or malformed one.

    Grammar (scip.proto): `<scheme> <manager> <package> <version> <descriptors>`, where a
    space inside the first four fields is written as two spaces.
    """
    if symbol.startswith("local "):
        return None
    rest = symbol
    for _ in range(4):
        rest = _skip_field(rest)
        if rest is None:
            return None
    try:
        return list(_descriptors(rest))
    except ValueError:
        return None


def _skip_field(text: str) -> str | None:
    pos = 0
    while pos < len(text):
        if text[pos] == " ":
            if text[pos + 1 : pos + 2] == " ":
                pos += 2  # an escaped space
                continue
            return text[pos + 1 :]
        pos += 1
    return None


_SUFFIXES = {"/": "namespace", "#": "type", ".": "term", ":": "meta", "!": "macro"}


def _descriptors(text: str) -> Iterable[Descriptor]:
    pos = 0
    while pos < len(text):
        if text[pos] == "(":  # parameter: `(name)`
            name, pos = _name(text, pos + 1)
            pos = _expect(text, pos, ")")
            yield Descriptor(name, "parameter")
        elif text[pos] == "[":  # type parameter: `[name]`
            name, pos = _name(text, pos + 1)
            pos = _expect(text, pos, "]")
            yield Descriptor(name, "type_parameter")
        else:
            name, pos = _name(text, pos)
            if pos < len(text) and text[pos] == "(":  # method: `name(disambiguator).`
                end = text.index(")", pos)
                pos = _expect(text, end + 1, ".")
                yield Descriptor(name, "method")
            elif pos < len(text) and text[pos] in _SUFFIXES:
                yield Descriptor(name, _SUFFIXES[text[pos]])
                pos += 1
            else:
                raise ValueError(f"bad descriptor at {pos} in {text!r}")


def _name(text: str, pos: int) -> tuple[str, int]:
    if pos < len(text) and text[pos] == "`":  # escaped name; a doubled backtick is literal
        out = []
        pos += 1
        while pos < len(text):
            if text[pos] == "`":
                if text[pos + 1 : pos + 2] == "`":
                    out.append("`")
                    pos += 2
                    continue
                return "".join(out), pos + 1
            out.append(text[pos])
            pos += 1
        raise ValueError("unterminated backtick name")
    start = pos
    while pos < len(text) and (text[pos].isalnum() or text[pos] in "_+-$"):
        pos += 1
    return text[start:pos], pos


def _expect(text: str, pos: int, char: str) -> int:
    if pos >= len(text) or text[pos] != char:
        raise ValueError(f"expected {char!r} at {pos} in {text!r}")
    return pos + 1


def qualname(descriptors: Sequence[Descriptor]) -> str:
    """CodeAtlas qualname: type, term and method names joined with dots."""
    return ".".join(d.name for d in descriptors if d.suffix in ("type", "term", "method"))


def symbol_kind(descriptors: Sequence[Descriptor]) -> str | None:
    """'function' for a function or method symbol, 'class' for a type, else None."""
    if not descriptors:
        return None
    last = descriptors[-1].suffix
    return {"method": "function", "type": "class"}.get(last)


# Indexes -------------------------------------------------------------------------------


def path_prefix(index: Index, repo_root_uri: str) -> str:
    """Folder of the index's project inside the repo, so its paths become repo-relative.

    scip-typescript runs once per tsconfig folder and writes paths relative to it.
    """
    root = PurePosixPath(_uri_path(repo_root_uri))
    project = PurePosixPath(_uri_path(index.project_root)) if index.project_root else root
    try:
        rel = project.relative_to(root)
    except ValueError:
        return ""
    return "" if str(rel) == "." else f"{rel}/"


def _uri_path(uri: str) -> str:
    return unquote(urlparse(uri).path) if uri.startswith("file:") else uri


def collect_definitions(indexes: Sequence[tuple[Index, str]]) -> dict[str, Definition]:
    """Definitions of functions, methods and classes by SCIP symbol."""
    found: dict[str, Definition] = {}
    for index, prefix in indexes:
        for document in index.documents:
            path = prefix + document.relative_path
            for occ in document.occurrences:
                if not occ.is_definition or occ.symbol in found:
                    continue
                descriptors = parse_descriptors(occ.symbol)
                kind = symbol_kind(descriptors) if descriptors else None
                if kind is None or descriptors is None:
                    continue
                span = occ.enclosing_range or occ.range
                found[occ.symbol] = Definition(
                    key=f"{path}::{qualname(descriptors)}",
                    kind=kind,
                    path=path,
                    start_line=span[0] + 1,
                    end_line=span[2] + 1,
                )
    return found


def collect_references(
    indexes: Sequence[tuple[Index, str]],
    definitions: dict[str, Definition],
    nodes: Iterable[GraphNode] = (),
) -> list[Reference]:
    """One reference per (caller, callee) pair, at the first line it occurs."""
    scopes = _scopes(definitions.values(), nodes)
    first: dict[tuple[str, str], int] = {}
    for index, prefix in indexes:
        for document in index.documents:
            path = prefix + document.relative_path
            for occ in document.occurrences:
                target = definitions.get(occ.symbol)
                if occ.is_definition or target is None or target.kind != "function":
                    continue
                line = occ.range[0] + 1
                caller = innermost(scopes.get(path, []), line)
                if caller is None:
                    continue  # module level: imports, re-exports, registries
                pair = (caller, target.key)
                first[pair] = min(first.get(pair, line), line)
    return [Reference(src, dst, line) for (src, dst), line in sorted(first.items())]


Scope = tuple[int, int, int, str]  # (start, end, preference, key); lower preference wins ties


def _scopes(
    definitions: Iterable[Definition], nodes: Iterable[GraphNode]
) -> dict[str, list[Scope]]:
    by_path: dict[str, list[Scope]] = {}
    for node in nodes:
        if node.kind in SCOPE_KINDS and node.start_line > 0:
            by_path.setdefault(node.path, []).append(
                (node.start_line, node.end_line, 0, node.key)
            )
    for d in definitions:
        if d.kind == "function":
            by_path.setdefault(d.path, []).append((d.start_line, d.end_line, 1, d.key))
    return by_path


def innermost(scopes: Sequence[Scope], line: int) -> str | None:
    """Key of the smallest scope holding `line`; a node-list scope wins a tie."""
    holding = [s for s in scopes if s[0] <= line <= s[1]]
    if not holding:
        return None
    return min(holding, key=lambda s: (s[1] - s[0], s[2]))[3]


# Output --------------------------------------------------------------------------------


def oracle_graph(
    snapshot: dict[str, object],
    indexes: Sequence[tuple[Index, str]],
    nodes: Iterable[GraphNode] = (),
    errors: Sequence[str] = (),
) -> dict[str, object]:
    """The oracle file: SCIP definitions as nodes and references as `calls` edges."""
    node_list = list(nodes)
    definitions = collect_definitions(indexes)
    references = collect_references(indexes, definitions, node_list)
    out_nodes: dict[str, dict[str, object]] = {}
    for index, prefix in indexes:
        for document in index.documents:
            path = prefix + document.relative_path
            out_nodes[f"{path}::"] = _node_dict(f"{path}::", "module", path, 1, 1)
    for d in definitions.values():
        out_nodes[d.key] = _node_dict(d.key, d.kind, d.path, d.start_line, d.end_line)
    # Callers found only through the node list (test cases) must be nodes too, or the
    # scorer would treat their edges as out of scope.
    for node in node_list:
        if any(r.src_key == node.key for r in references) and node.key not in out_nodes:
            out_nodes[node.key] = _node_dict(
                node.key, node.kind, node.path, node.start_line, node.end_line
            )
    edges = [
        {"src_key": r.src_key, "dst_key": r.dst_key, "kind": "calls", "confidence": 1.0,
         "resolution": RESOLUTION, "line": r.line}
        for r in references
    ]
    return {"snapshot": snapshot, "nodes": list(out_nodes.values()), "edges": edges,
            "errors": list(errors)}


def _node_dict(key: str, kind: str, path: str, start: int, end: int) -> dict[str, object]:
    return {"key": key, "kind": kind, "language": language_of_path(path), "path": path,
            "span": {"start_line": start, "end_line": end}}
