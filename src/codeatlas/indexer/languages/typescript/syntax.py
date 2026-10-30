"""Small tree-sitter helpers shared by every TypeScript/JavaScript extraction module."""

from __future__ import annotations

import re
from collections.abc import Iterator

from tree_sitter import Node as TSNode

from codeatlas.models import Span

NodeId = tuple[int, int, str]

# How sure we are about what a string-like expression holds; ordered from best to worst.
LITERAL, TEMPLATE, DYNAMIC = "literal", "template", "dynamic"
_KIND_RANK = {LITERAL: 0, TEMPLATE: 1, DYNAMIC: 2}

_JSDOC_LINE = re.compile(r"^\s*(/\*\*|\*/|\*)?\s?")


def ident(node: TSNode) -> NodeId:
    """A hashable identity for a tree-sitter node (nodes themselves are re-created on access)."""
    return (node.start_byte, node.end_byte, node.type)


def text(node: TSNode, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")


def compact(node: TSNode, source: bytes) -> str:
    """Text with all whitespace removed: `this.repo\n  .save` becomes `this.repo.save`."""
    return "".join(text(node, source).split())


def line(node: TSNode) -> int:
    return node.start_point[0] + 1


def span(node: TSNode) -> Span:
    start, end = node.start_point, node.end_point
    return Span(start[0] + 1, end[0] + 1, start[1], end[1])


def walk(node: TSNode) -> Iterator[TSNode]:
    """Every named node under `node`, in source order (iterative: deep files must not recurse)."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.named_children))


def string_value(node: TSNode | None, source: bytes) -> tuple[str, str] | None:
    """`(text, kind)` for a string or template literal; None for anything else.

    Literals lose their quotes; templates lose their backticks but keep `${...}`, so a
    base URL can be prefixed and the linker can still see where the parameters are.
    """
    if node is None:
        return None
    if node.type == "string":
        return text(node, source)[1:-1], LITERAL
    if node.type == "template_string":
        inner = text(node, source)[1:-1]
        has_substitution = any(c.type == "template_substitution" for c in node.named_children)
        return inner, TEMPLATE if has_substitution else LITERAL
    return None


def literal_string(node: TSNode | None, source: bytes) -> str | None:
    """The value of a string with no substitutions, the only kind a module path can be."""
    value = string_value(node, source)
    return value[0] if value and value[1] == LITERAL else None


def worst_kind(*kinds: str) -> str:
    return max(kinds, key=_KIND_RANK.__getitem__)


def expression_value(node: TSNode, source: bytes) -> tuple[str, str]:
    """A URL-like argument: a string or template, otherwise the expression as written."""
    return string_value(node, source) or (" ".join(text(node, source).split()), DYNAMIC)


def arguments(call: TSNode) -> list[TSNode]:
    args = call.child_by_field_name("arguments")
    if args is None:
        return []
    return [a for a in args.named_children if a.type != "comment"]


def object_property(obj: TSNode, name: str, source: bytes) -> TSNode | None:
    """The value of `name: value` (or shorthand `name`) in an object literal."""
    for child in obj.named_children:
        if child.type == "pair":
            key = child.child_by_field_name("key")
            if key is not None and text(key, source).strip("'\"") == name:
                return child.child_by_field_name("value")
        elif child.type == "shorthand_property_identifier" and text(child, source) == name:
            return child
    return None


def has_token(node: TSNode, token: str) -> bool:
    """Whether an anonymous keyword such as `async` is a direct child of `node`."""
    return any(not c.is_named and c.type == token for c in node.children)


def signature(start: TSNode, body: TSNode | None, source: bytes) -> str | None:
    """Text from `start` to the body, whitespace collapsed, as T00's tags tier does it."""
    end = body.start_byte if body is not None else start.end_byte
    raw = source[start.start_byte : end].decode("utf-8", "replace")
    if body is None:
        raw = raw.split("\n", 1)[0]
    collapsed = " ".join(raw.split()).rstrip("{:= ").strip()
    return collapsed or None


def jsdoc(statement: TSNode, source: bytes) -> str | None:
    """The `/** ... */` comment directly above `statement`, without its markers."""
    comment = statement.prev_sibling
    if comment is None or comment.type != "comment":
        return None
    if comment.end_point[0] < statement.start_point[0] - 1:
        return None
    raw = text(comment, source)
    if not raw.startswith("/**"):
        return None
    lines = [_JSDOC_LINE.sub("", part).removesuffix("*/").rstrip() for part in raw.splitlines()]
    cleaned = "\n".join(lines).strip()
    return cleaned or None
