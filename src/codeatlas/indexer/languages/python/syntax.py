"""Small tree-sitter helpers shared by the Python extraction modules."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from tree_sitter import Node as TSNode

from codeatlas.models import Span

NodeId = tuple[int, int, str]

_LINE_BREAK = re.compile(r"\s*\\?\n\s*")  # a newline, with any `\` continuation


def ident(node: TSNode) -> NodeId:
    """A hashable identity for a tree-sitter node, stable within one parse."""
    return (node.start_byte, node.end_byte, node.type)


def text(node: TSNode, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")


def one_line(node: TSNode, source: bytes) -> str:
    """Source text with line breaks (and the indentation after them) removed.

    A call chain split over lines (`client \\` then `.get(url)`) reads as written on one
    line; spaces inside the line, such as those in a string argument, are kept.
    """
    return _LINE_BREAK.sub("", text(node, source)).strip()


def span(node: TSNode) -> Span:
    start, end = node.start_point, node.end_point
    return Span(start[0] + 1, end[0] + 1, start[1], end[1])


def line(node: TSNode) -> int:
    return node.start_point[0] + 1


def walk(root: TSNode) -> Iterator[TSNode]:
    """Every node in source order, without recursion (deep files must not overflow)."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


@dataclass(frozen=True, slots=True)
class StringValue:
    """A string literal's content without quotes or prefix, and whether it is an f-string."""

    content: str
    is_fstring: bool


def string_value(node: TSNode, source: bytes) -> StringValue | None:
    """The content of a `string` node; None for anything else (names, concatenations)."""
    if node.type != "string" or node.child_count < 2:
        return None
    start, end = node.children[0], node.children[-1]
    if start.type != "string_start" or end.type != "string_end":
        return None
    content = source[start.end_byte : end.start_byte].decode("utf-8", "replace")
    prefix = text(start, source).lower()
    is_fstring = "f" in prefix or any(c.type == "interpolation" for c in node.children)
    return StringValue(content, is_fstring)


def plain_string(node: TSNode | None, source: bytes) -> str | None:
    """The content of a string literal with no interpolation, else None."""
    if node is None:
        return None
    value = string_value(node, source)
    return value.content if value is not None and not value.is_fstring else None


def arguments(call: TSNode) -> tuple[list[TSNode], dict[str, TSNode]]:
    """Positional argument nodes and keyword argument values of a call."""
    positional: list[TSNode] = []
    keywords: dict[str, TSNode] = {}
    argument_list = call.child_by_field_name("arguments")
    if argument_list is None or argument_list.type != "argument_list":
        return positional, keywords
    for child in argument_list.named_children:
        if child.type == "comment":
            continue
        if child.type == "keyword_argument":
            name, value = child.child_by_field_name("name"), child.child_by_field_name("value")
            if name is not None and value is not None and name.text is not None:
                keywords[name.text.decode("utf-8", "replace")] = value
        else:
            positional.append(child)
    return positional, keywords


def argument(call: TSNode, position: int, name: str) -> TSNode | None:
    """One argument, given either by position or by keyword."""
    positional, keywords = arguments(call)
    if name in keywords:
        return keywords[name]
    return positional[position] if position < len(positional) else None


def keyword(call: TSNode, name: str) -> TSNode | None:
    """A keyword-only argument's value, such as `methods=[...]`."""
    return arguments(call)[1].get(name)


def callee_parts(call: TSNode, source: bytes) -> tuple[str, str, str | None] | None:
    """`(callee_text, name, receiver)` of a call: `self.repo.save` -> `save`, `self.repo`."""
    function = call.child_by_field_name("function")
    if function is None:
        return None
    callee = one_line(function, source)
    if function.type == "attribute":
        obj = function.child_by_field_name("object")
        attribute = function.child_by_field_name("attribute")
        if obj is not None and attribute is not None:
            return callee, text(attribute, source), one_line(obj, source)
    # A plain name, or something with no last segment (`handlers[0]()`, `make()()`).
    return callee, callee, None
