"""Receiver types from what the code declares: signatures, JSDoc and class fields (T20).

The raw items carry no assignments, so the only evidence of a type is written down:
`(repo: UserRepo)`, `@param {UserRepo} repo`, `constructor(private repo: UserRepo)`, or a
class field (`attrs["fields"]`, filled by `symbols.py`). Anything else stays unknown, and
an unknown receiver is resolved exactly as before (D-22).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from codeatlas.indexer.languages.typescript.resolver.names import Named, NameResolver
from codeatlas.indexer.languages.typescript.resolver.tables import Tables
from codeatlas.models import Node, NodeKind

MAX_CHAIN = 3  # `this.a.b.m()`: one declared type per hop, at most this many hops
MAX_LINEAGE = 6
_OPEN, _CLOSE = "([{<", ")]}>"
_MODIFIERS = frozenset({"public", "private", "protected", "readonly", "override"})
_NOT_A_CLASS = frozenset({
    "any", "unknown", "never", "object", "void", "null", "undefined", "string", "number",
    "boolean", "bigint", "symbol", "this", "Promise", "PromiseLike", "Array",
    "ReadonlyArray", "Object", "Function",
})
_NAME = re.compile(r"([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*(<.*>)?")
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_JSDOC_TEMPLATE = re.compile(r"@template\s+(?:\{[^}]*\}\s*)?([\w$,\s]+)")


@dataclass(frozen=True, slots=True)
class Param:
    type_text: str | None  # the annotation as written, or None
    is_property: bool = False  # `constructor(private repo: UserRepo)`


@dataclass(frozen=True, slots=True)
class Signature:
    params: dict[str, Param] = field(default_factory=dict)
    type_params: frozenset[str] = frozenset()


# --- reading the stored text -------------------------------------------------------


def split_top(text: str, sep: str) -> list[str]:
    """Split on `sep` outside brackets and strings; `=>` is never an `=` separator."""
    parts, depth, start, quote = [], 0, 0, ""
    for i, ch in enumerate(text):
        if quote:
            quote = "" if ch == quote and text[i - 1] != "\\" else quote
        elif ch in "'\"`":
            quote = ch
        elif ch in _OPEN:
            depth += 1
        elif ch in _CLOSE and not (ch == ">" and text[i - 1 : i] == "="):
            depth = max(0, depth - 1)
        elif ch == sep and depth == 0 and not (sep == "=" and text[i + 1 : i + 2] == ">"):
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def _group(text: str, opener: str) -> tuple[str, int] | None:
    """The inside of the first top-level `opener` group and the index after it."""
    begin = text.find(opener)
    if begin < 0:
        return None
    depth, quote = 0, ""
    for i in range(begin, len(text)):
        ch = text[i]
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "'\"`":
            quote = ch
        elif ch in _OPEN:
            depth += 1
        elif ch in _CLOSE and not (ch == ">" and text[i - 1] == "="):
            depth -= 1
            if depth == 0:
                return text[begin + 1 : i], i + 1
    return None


def parse_signature(text: str | None) -> Signature:
    """Parameters with their annotations, and the type parameters, of one signature."""
    if not text:
        return Signature()
    paren = text.find("(")
    head = text[:paren] if paren >= 0 else text
    generics = _group(head, "<")
    type_params = frozenset(_type_param_names(generics[0])) if generics else frozenset()
    found = _group(text[paren:], "(") if paren >= 0 else None
    if found is None:
        return Signature(type_params=type_params)
    params: dict[str, Param] = {}
    for part in split_top(found[0], ","):
        named = _param(part)
        if named is not None:
            params.setdefault(*named)
    return Signature(params, type_params)


def _param(text: str) -> tuple[str, Param] | None:
    """`private readonly repo?: UserRepo = x` -> ("repo", Param("UserRepo", True))."""
    text = split_top(text, "=")[0].strip()
    words = text.split()
    is_property = False
    while len(words) > 1 and words[0] in _MODIFIERS:
        is_property = True
        words = words[1:]
    text = " ".join(words).removeprefix("...")
    name_part, colon, annotation = text.partition(":")
    name = name_part.strip().rstrip("?")
    if not _IDENT.fullmatch(name):
        return None  # destructured: `{ a }: Opts`, `[x, y]`
    return name, Param(annotation.strip() or None if colon else None, is_property)


def class_type_params(cls: Node) -> frozenset[str]:
    """`class Box<T>`: the type parameters written after the class name."""
    text = cls.signature or ""
    for word in (" extends ", " implements "):
        text = text.split(word, 1)[0]
    found = _group(text, "<")
    names = set(_type_param_names(found[0])) if found else set()
    return frozenset(names | jsdoc_templates(cls.docstring))


def _type_param_names(text: str) -> list[str]:
    names = []
    for part in split_top(text, ","):
        match = _IDENT.match(part.strip())
        if match:
            names.append(match.group(0))
    return names


def jsdoc_params(doc: str | None) -> dict[str, str]:
    """`@param {UserRepo} repo`, `@param {UserRepo} [repo=x]` -> {"repo": "UserRepo"}."""
    found: dict[str, str] = {}
    for chunk in (doc or "").split("@param")[1:]:
        braced = _group(chunk, "{")
        if braced is None or chunk[: chunk.find("{")].strip():
            continue
        match = _IDENT.match(chunk[braced[1]:].strip().lstrip("[").strip())
        if match:
            found.setdefault(match.group(0), braced[0].strip())
    return found


def jsdoc_templates(doc: str | None) -> set[str]:
    names: set[str] = set()
    for match in _JSDOC_TEMPLATE.finditer(doc or ""):
        names.update(n for n in re.split(r"[\s,]+", match.group(1).strip()) if n)
    return names


def type_name(text: str | None, type_params: frozenset[str] = frozenset()) -> str | None:
    """The one class a type names: `X`, `ns.X`, `X<T>`, `X | null`, JSDoc `?X` or `X=`.

    Unions of two types, intersections, arrays, promises, object and function types,
    primitives and type parameters name no class, so they give None.
    """
    text = _unwrap((text or "").strip().removeprefix("?").removeprefix("!").removesuffix("="))
    members = [_unwrap(m) for m in split_top(text, "|") if m.strip()]
    members = [m for m in members if m not in ("null", "undefined", "void")]
    if len(members) != 1:
        return None
    text = members[0]
    if len(split_top(text, "&")) > 1 or text.endswith("]"):
        return None
    match = _NAME.fullmatch(text)
    if match is None:
        return None
    name = match.group(1)
    head = name.split(".")[0]
    if head in type_params or name in _NOT_A_CLASS:
        return None
    return name


def _unwrap(text: str) -> str:
    """`((X))` -> `X`: parentheses around a whole type change nothing."""
    text = text.strip()
    while text.startswith("(") and _group(text, "(") == (text[1:-1], len(text)):
        text = text[1:-1].strip()
    return text


# --- from a receiver to a class ----------------------------------------------------


class Typer:
    """Turns declared types into repository classes, for receiver calls."""

    def __init__(
        self, tables: Tables, names: NameResolver, bases: Callable[[Node], list[Named]]
    ) -> None:
        self._t = tables
        self._names = names
        self._bases = bases
        self._signatures: dict[str, Signature] = {}

    def signature(self, node: Node) -> Signature:
        cached = self._signatures.get(node.key)
        if cached is None:
            cached = self._signatures[node.key] = parse_signature(node.signature)
        return cached

    def receiver_class(self, segments: list[str], caller: Node, cls: Node | None) -> Node | None:
        """The class of `this.repo`, `repo` or `repo.inner`, or None when not declared."""
        if len(segments) > MAX_CHAIN + 1:
            return None
        head = segments[0]
        current = cls if head == "this" else self.param_class(caller, head, cls)
        for attr in segments[1:]:
            if current is None:
                return None
            current = self.field_class(current, attr)
        return current if head != "this" or len(segments) > 1 else None

    def param_class(self, caller: Node, name: str, cls: Node | None) -> Node | None:
        """Nearest declaration wins: an untyped inner parameter hides a typed outer one."""
        type_params = self._type_params(caller, cls)
        for function in self._scopes(caller):
            declared = self._declared(function)
            if name in declared:
                return self._class_named(function.path, declared[name], type_params)
        return None

    def field_class(self, cls: Node, attr: str) -> Node | None:
        """`this.attr` on `cls`: a field, a parameter property, or a same-name constructor
        parameter; the class first, then its bases, nearest first."""
        for klass in self._lineage(cls):
            fields = klass.attrs.get("fields")
            type_params = class_type_params(klass)
            if isinstance(fields, dict) and attr in fields:
                return self._class_named(klass.path, str(fields[attr]), type_params)
            ctor = self._t.method(klass.key, "constructor")
            if ctor is not None:
                declared = self._declared(ctor)
                if attr in declared:
                    return self._class_named(ctor.path, declared[attr], type_params)
        return None

    # --- helpers -----------------------------------------------------------------

    def _declared(self, function: Node) -> dict[str, str | None]:
        """Parameter name -> type text: the annotation, else the JSDoc `@param`."""
        jsdoc = jsdoc_params(function.docstring)
        return {
            name: param.type_text or jsdoc.get(name)
            for name, param in self.signature(function).params.items()
        }

    def _scopes(self, caller: Node) -> list[Node]:
        """The caller and the functions written around it, innermost first."""
        found = [caller] if caller.kind is NodeKind.FUNCTION else []
        parts = caller.qualname.split(".")
        for size in range(len(parts) - 1, 0, -1):
            node = self._t.nodes.get(f"{caller.path}::{'.'.join(parts[:size])}")
            if node is not None and node.kind is NodeKind.FUNCTION:
                found.append(node)
        return found

    def _type_params(self, caller: Node, cls: Node | None) -> frozenset[str]:
        names: set[str] = set(class_type_params(cls)) if cls is not None else set()
        for function in self._scopes(caller):
            names |= self.signature(function).type_params | jsdoc_templates(function.docstring)
        return frozenset(names)

    def _class_named(
        self, path: str, text: str | None, type_params: frozenset[str]
    ) -> Node | None:
        name = type_name(text, type_params)
        found = self._names.resolve(name, path) if name else None
        node = found.node if found is not None else None
        return node if node is not None and node.kind is NodeKind.CLASS else None

    def _lineage(self, cls: Node) -> list[Node]:
        """The class and its repository base classes, nearest first, without repeats."""
        order, queue, seen = [], [cls], {cls.key}
        while queue and len(order) <= MAX_LINEAGE:
            klass = queue.pop(0)
            order.append(klass)
            for base in self._bases(klass):
                node = base.node
                if node is not None and node.kind is NodeKind.CLASS and node.key not in seen:
                    seen.add(node.key)
                    queue.append(node)
        return order
