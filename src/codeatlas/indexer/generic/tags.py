"""The structural tier's adapter: one class that works for any grammar with a tags query.

A tags query marks definitions (`@definition.function`, `@definition.class`, ...) and call
sites (`@reference.call`), each with a `@name`. This adapter turns those captures into
nodes and raw calls, nesting them by byte range: the innermost enclosing definition is a
method's owner and a call's caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from tree_sitter import Node as TSNode
from tree_sitter import Parser, Query, QueryCursor

from codeatlas.indexer.generic.grammars import GrammarSpec, load_language, load_tags_query
from codeatlas.models import (
    Node,
    NodeKind,
    ParseResult,
    RawCall,
    Span,
    Tier,
    make_key,
    make_node_id,
)

_DEFINITION_KINDS = {
    "definition.function": NodeKind.FUNCTION,
    "definition.method": NodeKind.FUNCTION,
    "definition.class": NodeKind.CLASS,
    "definition.interface": NodeKind.INTERFACE,
}
_CALL_CAPTURES = {"reference.call", "reference.send"}  # C# upstream names method calls "send"
_MAX_ERRORS = 5
_MAX_SIGNATURE = 300


@dataclass(slots=True)
class _Definition:
    """A definition found by the query, before it becomes a Node."""

    node: TSNode
    name: str
    kind: NodeKind
    qualname: str = ""
    owner_key: str | None = None
    receiver: str | None = None


class TagsAdapter:
    """A `LanguageAdapter` built from one grammar and its tags query (tier STRUCTURAL)."""

    tier = Tier.STRUCTURAL

    def __init__(self, spec: GrammarSpec, extensions: tuple[str, ...] = ()) -> None:
        self.language = spec.name
        self.extensions = extensions
        self._spec = spec
        language = load_language(spec)
        self._parser = Parser(language)
        self._query = Query(language, load_tags_query(spec))
        self._disable_unsupported_patterns()

    def parse(self, path: str, source: bytes, snapshot_id: str) -> ParseResult:
        """Never raises: a syntax error or an extraction bug is recorded in `errors`."""
        module = module_node(path, self.language, source, snapshot_id)
        try:
            tree = self._parser.parse(source)
            nodes, calls = self._extract(tree.root_node, path, snapshot_id)
            errors = syntax_errors(tree.root_node)
        except Exception as exc:  # the contract forbids raising here; record it instead
            return ParseResult(
                path=path,
                language=self.language,
                tier=self.tier,
                nodes=(module,),
                errors=(f"extraction failed: {exc!r}",),
            )
        return ParseResult(
            path=path,
            language=self.language,
            tier=self.tier,
            nodes=(module, *nodes),
            calls=tuple(calls),
            errors=tuple(errors),
        )

    def _disable_unsupported_patterns(self) -> None:
        """Turn off patterns guarded by predicates py-tree-sitter cannot evaluate.

        Ruby's tags query marks every identifier as a call unless `(#is-not? local)` says it
        is a local variable. Ignoring that predicate would turn every variable read into a
        call, so the pattern is dropped instead: fewer calls, but no invented ones.
        """
        for index in range(self._query.pattern_count):
            if self._query.pattern_assertions(index):
                self._query.disable_pattern(index)

    def _extract(
        self, root: TSNode, path: str, snapshot_id: str
    ) -> tuple[list[Node], list[RawCall]]:
        matches = QueryCursor(self._query).matches(root)
        definitions = self._definitions(matches)
        self._name_definitions(definitions, path)
        module_key = make_key(path, "")
        nodes = [self._to_node(d, path, snapshot_id) for d in definitions]
        calls = self._calls(matches, definitions, path, module_key)
        return nodes, calls

    def _definitions(self, matches: list[tuple[int, dict[str, list[TSNode]]]]) -> list[_Definition]:
        """One definition per name, outermost first, so parents are seen before children.

        Two patterns can claim the same name: a Rust function inside an `impl` matches both
        the function and the method pattern, and some query versions capture the whole
        `impl` body as the method. The smallest captured node is the definition itself.
        """
        found: dict[tuple[int, int], _Definition] = {}
        for _, captures in matches:
            names = captures.get("name")
            if not names:
                continue
            for capture, nodes in captures.items():
                node = nodes[0]
                kind = self._definition_kind(capture, node)
                if kind is None:
                    continue
                name_span = (names[0].start_byte, names[0].end_byte)
                known = found.get(name_span)
                if known is None or _size(node) < _size(known.node):
                    found[name_span] = _Definition(node=node, name=_text(names[0]), kind=kind)
        return sorted(found.values(), key=lambda d: (d.node.start_byte, -d.node.end_byte))

    def _definition_kind(self, capture: str, node: TSNode) -> NodeKind | None:
        if capture in _DEFINITION_KINDS:
            return _DEFINITION_KINDS[capture]
        if capture == "definition.type":
            defined = node.child_by_field_name("type")
            return self._spec.type_kinds.get(defined.type) if defined is not None else None
        return None  # modules (the file is the module), constants, fields, macros, ...

    def _name_definitions(self, definitions: list[_Definition], path: str) -> None:
        """Set qualnames and owner keys, using the innermost enclosing definition."""
        stack: list[_Definition] = []
        seen: dict[str, int] = {}
        for d in definitions:
            while stack and not _contains(stack[-1].node, d.node):
                stack.pop()
            parent = stack[-1] if stack else None
            if parent is not None:
                d.qualname = f"{parent.qualname}.{d.name}"
                if d.kind is NodeKind.FUNCTION and parent.kind in _OWNER_KINDS:
                    d.owner_key = make_key(path, parent.qualname)
            else:
                d.receiver = self._owner_type(d.node) if d.kind is NodeKind.FUNCTION else None
                d.qualname = f"{d.receiver}.{d.name}" if d.receiver else d.name
            d.qualname = _unique(d.qualname, seen)
            stack.append(d)
        classes = {d.qualname for d in definitions if d.kind in _OWNER_KINDS}
        for d in definitions:
            if d.receiver is not None and d.receiver in classes:
                d.owner_key = make_key(path, d.receiver)

    def _owner_type(self, node: TSNode) -> str | None:
        """The type a method belongs to when it is written outside the type's body.

        Go writes `func (s *Server) Start()`; Rust writes `impl Server { fn start() }`.
        """
        current: TSNode | None = node
        while current is not None:
            field_name = self._spec.owner_fields.get(current.type)
            if field_name is not None:
                holder = current.child_by_field_name(field_name)
                return _first_type_name(holder) if holder is not None else None
            current = current.parent
        return None

    def _to_node(self, d: _Definition, path: str, snapshot_id: str) -> Node:
        key = make_key(path, d.qualname)
        attrs: dict[str, object] = {"receiver": d.receiver} if d.receiver else {}
        return Node(
            id=make_node_id(snapshot_id, key),
            key=key,
            snapshot_id=snapshot_id,
            kind=d.kind,
            language=self.language,
            name=d.name,
            qualname=d.qualname,
            path=path,
            span=_span(d.node),
            signature=_signature(d.node),
            owner_key=d.owner_key,
            attrs=attrs,
        )

    def _calls(
        self,
        matches: list[tuple[int, dict[str, list[TSNode]]]],
        definitions: list[_Definition],
        path: str,
        module_key: str,
    ) -> list[RawCall]:
        calls: dict[tuple[int, int], RawCall] = {}
        for _, captures in matches:
            names = captures.get("name")
            call_nodes = [n for c in _CALL_CAPTURES for n in captures.get(c, [])]
            if not names or not call_nodes:
                continue
            name_node = names[0]
            span = (name_node.start_byte, name_node.end_byte)
            if span in calls:
                continue
            callee = _callee_text(call_nodes[0], name_node)
            name = _text(name_node)
            caller = _innermost(definitions, name_node)
            calls[span] = RawCall(
                caller_key=make_key(path, caller.qualname) if caller else module_key,
                callee_text=callee,
                name=name,
                receiver=_receiver(callee, name),
                line=name_node.start_point[0] + 1,
            )
        return [calls[s] for s in sorted(calls)]


_OWNER_KINDS = {NodeKind.CLASS, NodeKind.INTERFACE}


def module_node(path: str, language: str, source: bytes, snapshot_id: str) -> Node:
    """The node every file gets, whatever its tier; always first in `ParseResult.nodes`."""
    key = make_key(path, "")
    lines = source.count(b"\n") + (0 if source.endswith(b"\n") or not source else 1)
    return Node(
        id=make_node_id(snapshot_id, key),
        key=key,
        snapshot_id=snapshot_id,
        kind=NodeKind.MODULE,
        language=language,
        name=PurePosixPath(path).name,
        qualname="",
        path=path,
        span=Span(start_line=1, end_line=max(lines, 1)),
    )


def syntax_errors(root: TSNode) -> list[str]:
    """Up to five readable messages for ERROR and MISSING nodes, plus a count of the rest."""
    if not root.has_error:
        return []
    found: list[str] = []
    total = 0
    stack = [root]
    while stack:
        node = stack.pop()
        if node.is_missing or node.is_error:
            total += 1
            if len(found) < _MAX_ERRORS:
                line = node.start_point[0] + 1
                what = f"missing {node.type!r}" if node.is_missing else "syntax error"
                found.append(f"{what} at line {line}")
            continue
        if node.has_error:
            stack.extend(reversed(node.children))
    if total > len(found):
        found.append(f"... and {total - len(found)} more syntax errors")
    return found or ["syntax error (location unknown)"]


def _text(node: TSNode) -> str:
    return (node.text or b"").decode("utf-8", errors="replace")


def _size(node: TSNode) -> int:
    return node.end_byte - node.start_byte


def _contains(outer: TSNode, inner: TSNode) -> bool:
    return outer.start_byte <= inner.start_byte and inner.end_byte <= outer.end_byte


def _innermost(definitions: list[_Definition], node: TSNode) -> _Definition | None:
    best: _Definition | None = None
    for d in definitions:  # outermost first, so the last match is the innermost
        if _contains(d.node, node):
            best = d
    return best


def _unique(qualname: str, seen: dict[str, int]) -> str:
    """Keep keys unique when a name repeats in one file (Java overloads, two Rust impls)."""
    count = seen.get(qualname, 0) + 1
    seen[qualname] = count
    return qualname if count == 1 else f"{qualname}#{count}"


def _first_type_name(node: TSNode) -> str | None:
    """The first type name inside `node`: `Server` in `(s *Server)` or in `Server<T>`."""
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type == "type_identifier":
            return _text(current)
        stack.extend(reversed(current.children))
    return None


def _callee_text(call: TSNode, name: TSNode) -> str:
    """The call target as written, from the start of the call to the end of its name.

    Some queries capture the argument list instead of the call (Java, JavaScript member
    calls); the call is then its parent. Whitespace inside a chained call is dropped.
    """
    if not _contains(call, name) and call.parent is not None:
        call = call.parent
    if not _contains(call, name):
        return _text(name)
    raw = (call.text or b"")[: name.end_byte - call.start_byte]
    return re.sub(r"\s+", "", raw.decode("utf-8", errors="replace"))


def _receiver(callee: str, name: str) -> str | None:
    """Everything before the last segment: `self.repo` for `self.repo.save`."""
    if not callee.endswith(name):
        return None
    receiver = callee[: -len(name)].rstrip(".:->?&")
    return receiver or None


def _span(node: TSNode) -> Span:
    # Points are read by index, not `.row`/`.column`: attribute access segfaults in
    # tree-sitter 0.26.0 after enough nodes. Indexing works on every supported version.
    return Span(
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        start_col=node.start_point[1],
        end_col=node.end_point[1],
    )


def _signature(node: TSNode) -> str | None:
    """The definition's header as written: everything before its body, on one line."""
    body = node.child_by_field_name("body")
    raw = node.text or b""
    if body is not None:
        raw = raw[: body.start_byte - node.start_byte]
    else:
        raw = raw.split(b"\n", 1)[0]
    text = " ".join(raw.decode("utf-8", errors="replace").split()).rstrip("{:; ").strip()
    return text[:_MAX_SIGNATURE] or None
