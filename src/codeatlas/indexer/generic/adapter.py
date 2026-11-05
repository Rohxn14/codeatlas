"""The structural tier: one adapter class, configured per language by a tags query.

Tags queries (`queries/tags.scm` in most tree-sitter grammars) mark definitions with
`@definition.<kind>` and calls with `@reference.call`, each with a `@name` capture.
They exist for code navigation on GitHub, so they are maintained upstream for many
languages; reading them generically gives every such language functions, classes and
name-level calls without writing an adapter per language.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath

from tree_sitter import Language, Parser, Query, QueryCursor
from tree_sitter import Node as TSNode

from codeatlas.models import (
    Node,
    NodeKind,
    ParseResult,
    RawCall,
    RawImport,
    Span,
    Tier,
    make_key,
    make_node_id,
)

# Tag kinds that become nodes. "type" is decided by the shape of the type (Go's
# `type X struct` and `type X interface` are both tagged `definition.type`).
_KIND_BY_TAG: dict[str, NodeKind] = {
    "class": NodeKind.CLASS,
    "interface": NodeKind.INTERFACE,
    "function": NodeKind.FUNCTION,
    "method": NodeKind.FUNCTION,
}
# Tags that are not nodes but still name a scope: `mod tests { fn a() }` gives `tests.a`.
_SCOPE_TAGS = frozenset({"module"})
_OWNER_KINDS = frozenset({NodeKind.CLASS, NodeKind.INTERFACE})

# Methods declared outside their type: Go puts the type in the receiver, Rust in the
# enclosing `impl` block. Node type -> field holding the owner's type.
_RECEIVER_FIELDS: dict[str, str] = {"method_declaration": "receiver"}
_IMPL_BLOCKS: dict[str, str] = {"impl_item": "type"}

# C and C++ tags queries tag the declarator (`h(void)`), which ends before the body, so
# no call would ever sit inside the function. Tagged node type -> the definition that
# holds it; the wider node is used only when it has a body (a prototype stays as it is).
_DEFINITION_HOLDERS: dict[str, str] = {"function_declarator": "function_definition"}
_DECLARATOR_WRAPPERS = frozenset(
    {"pointer_declarator", "reference_declarator", "parenthesized_declarator",
     "attributed_declarator"}
)

_QUERIES_DIR = Path(__file__).resolve().parent.parent / "queries"
_MAX_ERRORS = 20
_CALL_SEPARATOR = re.compile(r"(\?\.|\.|::|->)$")
_COMMENT_MARKERS = re.compile(r"^\s*(///?|/\*\*?|\*/?|#|--)\s?")

NodeId = tuple[int, int, str]
Matches = list[tuple[int, dict[str, list[TSNode]]]]


def _ident(node: TSNode) -> NodeId:
    return (node.start_byte, node.end_byte, node.type)


@dataclass(slots=True)
class _Definition:
    node: TSNode
    name: str
    tag: str
    kind: NodeKind | None  # None for scope-only tags such as modules
    signature: str | None = None
    qualname: str = ""
    owner_key: str | None = None
    attrs: dict[str, object] = field(default_factory=dict)


class TagsAdapter:
    """Structural-tier adapter: definitions and name-level calls from a tags query."""

    tier: Tier = Tier.STRUCTURAL

    def __init__(
        self,
        language: str,
        grammar: Language,
        tags_query: str,
        extensions: tuple[str, ...] = (),
        imports_query: str | None = None,
    ) -> None:
        self.language = language
        self.extensions = extensions
        self._parser = Parser(grammar)
        self._query = Query(grammar, tags_query)
        self._disable_unsupported_patterns()
        if imports_query is None:
            imports_query = _vendored_imports_query(language)
        self._imports_query = Query(grammar, imports_query) if imports_query else None

    def _disable_unsupported_patterns(self) -> None:
        """Turn off patterns guarded by `#is?` / `#is-not?`, which py-tree-sitter ignores.

        Ruby's tags query tags every bare identifier as a call unless `(#is-not? local)`
        says it is a local variable. Ignored, that filter would turn every variable read
        into a call, so the pattern is dropped: fewer calls, but no invented ones.
        """
        for index in range(self._query.pattern_count):
            if self._query.pattern_assertions(index):
                self._query.disable_pattern(index)

    def parse(self, path: str, source: bytes, snapshot_id: str) -> ParseResult:
        """Never raises: a failure anywhere still yields the module node and an error."""
        module = module_node(path, self.language, source, snapshot_id)
        try:
            tree = self._parser.parse(source)
            errors = syntax_errors(tree.root_node)
            matches = QueryCursor(self._query).matches(tree.root_node)
            definitions = self._definitions(matches, source, path)
            nodes = [module, *self._nodes(definitions, path, source, snapshot_id)]
            calls = self._calls(tree.root_node, matches, source, path, definitions)
            imports, packages = self._imports(tree.root_node, source, module.key, definitions)
            if packages:
                attrs = {**module.attrs, "package": packages[0], "packages": packages}
                nodes[0] = replace(module, attrs=attrs)
        except Exception as exc:  # defensive: a grammar bug must not stop indexing
            return ParseResult(
                path, self.language, self.tier, (module,), errors=(f"adapter failed: {exc}",)
            )
        return ParseResult(
            path,
            self.language,
            self.tier,
            tuple(nodes),
            imports=tuple(imports),
            calls=tuple(calls),
            errors=errors,
        )

    # Imports

    def _imports(
        self,
        root: TSNode,
        source: bytes,
        module_key: str,
        definitions: dict[NodeId, _Definition] | None = None,
    ) -> tuple[list[RawImport], list[str]]:
        """Imports and the declared packages, from `imports.scm` (see queries/README.md)."""
        if self._imports_query is None:
            return [], []
        statements: dict[NodeId, dict[str, list[TSNode]]] = {}
        package_names: list[TSNode] = []
        for _, captures in QueryCursor(self._imports_query).matches(root):
            package_names += captures.get("package.name", [])[:1]
            if "import" in captures and "import.target" in captures:
                merged = statements.setdefault(_ident(captures["import"][0]), {})
                for capture, nodes in captures.items():
                    merged.setdefault(capture, []).extend(nodes)
        imports = [_raw_import(c, source, module_key) for c in statements.values()]
        packages = _packages(package_names, source, definitions or {})
        return sorted(imports, key=lambda i: i.line), packages

    # Definitions

    @staticmethod
    def _definitions(matches: Matches, source: bytes, path: str) -> dict[NodeId, _Definition]:
        found: dict[NodeId, _Definition] = {}
        for _, captures in matches:
            for capture, nodes in captures.items():
                if not capture.startswith("definition.") or "name" not in captures:
                    continue
                tag = capture.removeprefix("definition.")
                definition = _make_definition(nodes[0], captures["name"][0], tag, source)
                if definition is None:
                    continue
                key = _ident(definition.node)
                # Rust tags a method twice (as method and function); the method wins.
                if key not in found or found[key].tag != "method":
                    found[key] = definition
        ordered = dict(sorted(found.items(), key=lambda item: (item[0][0], -item[0][1])))
        _assign_qualnames(ordered, path, source)
        return ordered

    def _nodes(
        self,
        definitions: dict[NodeId, _Definition],
        path: str,
        source: bytes,
        snapshot_id: str,
    ) -> list[Node]:
        nodes = []
        for definition in definitions.values():
            if definition.kind is None:
                continue
            key = make_key(path, definition.qualname)
            nodes.append(
                Node(
                    id=make_node_id(snapshot_id, key),
                    key=key,
                    snapshot_id=snapshot_id,
                    kind=definition.kind,
                    language=self.language,
                    name=definition.name,
                    qualname=definition.qualname,
                    path=path,
                    span=_span(definition.node),
                    signature=definition.signature,
                    docstring=_leading_comment(definition.node, source),
                    owner_key=definition.owner_key,
                    attrs=definition.attrs,
                )
            )
        return nodes

    # Calls

    @staticmethod
    def _calls(
        root: TSNode,
        matches: Matches,
        source: bytes,
        path: str,
        definitions: dict[NodeId, _Definition],
    ) -> list[RawCall]:
        calls: dict[tuple[int, int], RawCall] = {}
        for _, captures in matches:
            if "reference.call" not in captures or "name" not in captures:
                continue
            name_node = captures["name"][0]
            call = _call_node(root, captures["reference.call"][0], name_node)
            callee = _compact(source[call.start_byte : name_node.end_byte])
            name = _text(name_node, source)
            receiver = None
            if callee.endswith(name) and len(callee) > len(name):
                receiver = _CALL_SEPARATOR.sub("", callee[: -len(name)]) or None
            calls[(call.start_byte, name_node.end_byte)] = RawCall(
                caller_key=_enclosing_key(call, definitions, path),
                callee_text=callee,
                name=name,
                receiver=receiver,
                line=call.start_point[0] + 1,
            )
        return [calls[k] for k in sorted(calls)]


def _packages(
    names: list[TSNode], source: bytes, definitions: dict[NodeId, _Definition]
) -> list[str]:
    """Every package the file declares, nested ones joined: `namespace A { namespace B }`
    is `A.B`. Kept in source order, without repeats.

    A declaration that only wraps others (`A` above) holds no code, so a package is kept
    only when a definition sits directly inside it. When no definition is inside any
    package declaration (Java's `package x;`, C#'s `namespace A;`, which are siblings of
    the code), every declared package is kept.
    """
    holders: dict[NodeId, str] = {}
    for name in sorted(names, key=lambda n: n.start_byte):  # outer declarations first
        declaration = name.parent
        if declaration is None:
            continue
        outer = _enclosing_holder(declaration, holders)
        own = _text(name, source)
        holders[_ident(declaration)] = f"{outer}.{own}" if outer else own
    used = {
        holder
        for definition in definitions.values()
        if definition.kind is not None
        and (holder := _enclosing_holder(definition.node, holders)) is not None
    }
    kept = [p for p in holders.values() if p in used] or list(holders.values())
    return list(dict.fromkeys(kept))


def _enclosing_holder(node: TSNode, holders: dict[NodeId, str]) -> str | None:
    parent = node.parent
    while parent is not None:
        if _ident(parent) in holders:
            return holders[_ident(parent)]
        parent = parent.parent
    return None


def _raw_import(captures: dict[str, list[TSNode]], source: bytes, module_key: str) -> RawImport:
    names = tuple((_text(n, source), None) for n in captures.get("import.name", []))
    if "import.wildcard" in captures:
        names += (("*", None),)
    alias = captures.get("import.alias")
    return RawImport(
        module_key=module_key,
        target=_text(captures["import.target"][0], source),
        names=names,
        alias=_text(alias[0], source) if alias else None,
        line=captures["import"][0].start_point[0] + 1,
    )


def _vendored_imports_query(language: str) -> str | None:
    path = _QUERIES_DIR / language / "imports.scm"
    return path.read_text(encoding="utf-8") if path.is_file() else None


class TextAdapter:
    """Text tier: the file is still a node, with the reason it was not parsed."""

    tier: Tier = Tier.TEXT

    def __init__(self, language: str, reason: str = "", extensions: tuple[str, ...] = ()) -> None:
        self.language = language
        self.extensions = extensions
        self.reason = reason

    def parse(self, path: str, source: bytes, snapshot_id: str) -> ParseResult:
        attrs: dict[str, object] = {"tier_reason": self.reason} if self.reason else {}
        module = module_node(path, self.language, source, snapshot_id, attrs)
        return ParseResult(path, self.language, self.tier, (module,))


# Helpers shared by both adapters


def module_node(
    path: str,
    language: str,
    source: bytes,
    snapshot_id: str,
    attrs: dict[str, object] | None = None,
) -> Node:
    """The node for the file itself, which every adapter emits first."""
    key = make_key(path, "")
    lines = source.count(b"\n") + (0 if source.endswith(b"\n") else 1)
    return Node(
        id=make_node_id(snapshot_id, key),
        key=key,
        snapshot_id=snapshot_id,
        kind=NodeKind.MODULE,
        language=language,
        name=PurePosixPath(path).name,
        qualname="",
        path=path,
        span=Span(1, max(lines, 1)),
        attrs=attrs or {},
    )


def syntax_errors(root: TSNode) -> tuple[str, ...]:
    """Describe the first few ERROR and MISSING nodes; tree-sitter parses around them."""
    if not root.has_error:
        return ()
    errors: list[str] = []
    stack = [root]
    while stack and len(errors) < _MAX_ERRORS:
        node = stack.pop()
        line, col = node.start_point[0] + 1, node.start_point[1]
        if node.is_missing:
            errors.append(f"syntax error: missing {node.type!r} at line {line}, column {col}")
        elif node.is_error:
            errors.append(f"syntax error at line {line}, column {col}")
            continue
        if node.has_error:
            stack.extend(reversed(node.children))
    return tuple(errors) or ("syntax error",)


def _make_definition(
    node: TSNode, name_node: TSNode, tag: str, source: bytes
) -> _Definition | None:
    name = _text(name_node, source)
    if tag in _SCOPE_TAGS:
        return _Definition(node, name, tag, None)
    kind = _type_kind(node) if tag == "type" else _KIND_BY_TAG.get(tag)
    if kind is None:
        return None
    # The signature stays the tagged node's text (`h(void)`): it feeds the `#hash` key
    # suffix, so widening the node to the whole definition must not change it.
    return _Definition(_definition_holder(node), name, tag, kind, _signature(node, source))


def _definition_holder(node: TSNode) -> TSNode:
    """The whole `function_definition` around a tagged C/C++ declarator, when it has a
    body; otherwise the tagged node itself.

    Only the definition's own declarator counts: `int (*f(void))(int)` wraps it in other
    declarators, but a function declarator in a parameter list is not the definition's.
    """
    holder_type = _DEFINITION_HOLDERS.get(node.type)
    if holder_type is None:
        return node
    child, parent = node, node.parent
    while parent is not None and parent.type in _DECLARATOR_WRAPPERS:
        child, parent = parent, parent.parent
    if parent is None or parent.type != holder_type:
        return node
    declarator = parent.child_by_field_name("declarator")
    if declarator is None or _ident(declarator) != _ident(child):
        return node
    return parent if parent.child_by_field_name("body") is not None else node


def _type_kind(node: TSNode) -> NodeKind | None:
    """`type X struct {}` is a class, `type X interface {}` an interface, aliases nothing."""
    shape = node.child_by_field_name("type")
    if shape is None:
        return None
    if "interface" in shape.type:
        return NodeKind.INTERFACE
    if "struct" in shape.type or "class" in shape.type:
        return NodeKind.CLASS
    return None


def _assign_qualnames(
    definitions: dict[NodeId, _Definition], path: str, source: bytes
) -> None:
    """Dotted qualnames from nesting, owners for methods, and unique keys per file."""
    parents = {key: _enclosing_definition(d.node, definitions) for key, d in definitions.items()}
    owners: dict[NodeId, str | None] = {}
    for key, definition in definitions.items():
        parent = parents[key]
        is_free_function = definition.kind is NodeKind.FUNCTION and (
            parent is None or parent.kind is None
        )
        owners[key] = _declared_owner(definition.node, source) if is_free_function else None
    suffixes = _duplicate_suffixes(definitions, parents, owners)
    for key, definition in definitions.items():  # outer definitions come first
        parent, owner = parents[key], owners[key]
        prefix = ".".join(p for p in (parent.qualname if parent else "", owner or "") if p)
        if owner:
            definition.attrs["receiver"] = owner
        qualname = f"{prefix}.{definition.name}" if prefix else definition.name
        definition.qualname = qualname + suffixes.get(key, "")
        if definition.kind is NodeKind.FUNCTION and parent and parent.kind in _OWNER_KINDS:
            definition.owner_key = make_key(path, parent.qualname)
    by_qualname = {d.qualname: d for d in definitions.values() if d.kind in _OWNER_KINDS}
    for key, definition in definitions.items():
        if owners[key] and definition.owner_key is None:
            owner_qualname = definition.qualname.rsplit(".", 1)[0]
            if owner_qualname in by_qualname:
                definition.owner_key = make_key(path, owner_qualname)


def _duplicate_suffixes(
    definitions: dict[NodeId, _Definition],
    parents: dict[NodeId, _Definition | None],
    owners: dict[NodeId, str | None],
) -> dict[NodeId, str]:
    """`#<hash of signature>` for every definition whose qualname would repeat.

    Overloads (`save(int)`, `save(String)`) and repeated impl blocks (two `fmt`) share a
    qualname. A hash of the signature keeps each key stable when another overload is
    added or moved; only identical signatures fall back to `-2`, `-3` by order.
    """
    groups: dict[tuple[NodeId | None, str | None, str], list[NodeId]] = {}
    for key, definition in definitions.items():
        parent = parents[key]
        scope = _ident(parent.node) if parent else None
        groups.setdefault((scope, owners[key], definition.name), []).append(key)
    suffixes: dict[NodeId, str] = {}
    for keys in groups.values():
        if len(keys) < 2:
            continue
        seen: dict[str, int] = {}
        for key in keys:
            signature = definitions[key].signature or definitions[key].name
            digest = hashlib.sha1(signature.encode(), usedforsecurity=False).hexdigest()[:4]
            seen[digest] = seen.get(digest, 0) + 1
            ordinal = f"-{seen[digest]}" if seen[digest] > 1 else ""
            suffixes[key] = f"#{digest}{ordinal}"
    return suffixes


def _enclosing_definition(
    node: TSNode, definitions: dict[NodeId, _Definition]
) -> _Definition | None:
    parent = node.parent
    while parent is not None:
        found = definitions.get(_ident(parent))
        if found is not None:
            return found
        parent = parent.parent
    return None


def _declared_owner(node: TSNode, source: bytes) -> str | None:
    """The type a method belongs to when it is declared outside it (Go, Rust)."""
    holder = None
    if node.type in _RECEIVER_FIELDS:
        holder = node.child_by_field_name(_RECEIVER_FIELDS[node.type])
    parent = node.parent
    while holder is None and parent is not None:
        if parent.type in _IMPL_BLOCKS:
            holder = parent.child_by_field_name(_IMPL_BLOCKS[parent.type])
            break
        parent = parent.parent
    if holder is None:
        return None
    type_name = _first_of_type(holder, "type_identifier")
    return _text(type_name, source) if type_name else None


def _first_of_type(node: TSNode, node_type: str) -> TSNode | None:
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type == node_type:
            return current
        stack.extend(reversed(current.children))
    return None


def _call_node(root: TSNode, reference: TSNode, name_node: TSNode) -> TSNode:
    """Some queries tag the argument list, not the call: take the node spanning both."""
    start = min(reference.start_byte, name_node.start_byte)
    end = max(reference.end_byte, name_node.end_byte)
    if start == reference.start_byte and end == reference.end_byte:
        return reference
    return root.descendant_for_byte_range(start, end) or reference


def _enclosing_key(node: TSNode, definitions: dict[NodeId, _Definition], path: str) -> str:
    """Key of the innermost definition around `node` that is a node, else the module key."""
    parent = node.parent
    while parent is not None:
        found = definitions.get(_ident(parent))
        if found is not None and found.kind is not None:
            return make_key(path, found.qualname)
        parent = parent.parent
    return make_key(path, "")


def _signature(node: TSNode, source: bytes) -> str | None:
    """The definition's header as one line: no body, no comments, whitespace collapsed.

    It feeds the `#hash` suffix for repeated names, so it must be the same text the deep
    adapters hash. A comment between a Python `def ...:` and its first statement, or inside
    the header, would otherwise change the key whenever someone edits the comment.
    """
    body = node.child_by_field_name("body")
    end = body.start_byte if body is not None else node.end_byte
    pieces, position = [], node.start_byte
    for comment in _comments_between(node, end):
        pieces.append(source[position : comment.start_byte])
        position = max(position, comment.end_byte)
    pieces.append(source[position:end])
    text = b"".join(pieces).decode("utf-8", "replace")
    if body is None:
        text = text.split("\n", 1)[0]
    text = " ".join(text.split()).rstrip("{:=; ").strip()
    return text or None


def _comments_between(node: TSNode, end: int) -> list[TSNode]:
    """Comment nodes inside `node` that start before byte `end`, in source order."""
    found: list[TSNode] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current.start_byte >= end:
            continue
        if "comment" in current.type:
            found.append(current)
        else:
            stack.extend(current.children)
    return sorted(found, key=lambda c: c.start_byte)


def _leading_comment(node: TSNode, source: bytes) -> str | None:
    """Comments directly above a definition, without blank lines in between."""
    lines: list[str] = []
    current, expected_row = node.prev_sibling, node.start_point[0]
    while current is not None and "comment" in current.type:
        if current.end_point[0] < expected_row - 1:
            break
        lines.insert(0, _text(current, source))
        expected_row = current.start_point[0]
        current = current.prev_sibling
    if not lines:
        return None
    cleaned = [
        _COMMENT_MARKERS.sub("", line).removesuffix("*/").rstrip()
        for line in "\n".join(lines).splitlines()
    ]
    text = "\n".join(line for line in cleaned if line.strip("*/ ")).strip()
    return text or None


def _span(node: TSNode) -> Span:
    return Span(
        node.start_point[0] + 1,
        node.end_point[0] + 1,
        node.start_point[1],
        node.end_point[1],
    )


def _text(node: TSNode, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _compact(raw: bytes) -> str:
    return "".join(raw.decode("utf-8", "replace").split())
