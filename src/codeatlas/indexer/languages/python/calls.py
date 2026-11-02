"""Every call expression in the file, as written, with the function it runs in."""

from __future__ import annotations

from tree_sitter import Node as TSNode

from codeatlas.indexer.languages.python.definitions import Scopes
from codeatlas.indexer.languages.python.syntax import callee_parts, line, one_line, walk
from codeatlas.models import RawCall


def collect_calls(root: TSNode, source: bytes, scopes: Scopes) -> list[RawCall]:
    """Calls in source order: `a().b()` gives `a().b` first, then `a` inside it.

    Calls in lambdas and comprehensions belong to the function around them, since
    neither is a definition with a key of its own.
    """
    calls = []
    for node in walk(root):
        if node.type == "decorator":
            bare = _bare_decorator_call(node, source, scopes)
            if bare is not None:
                calls.append(bare)
            continue
        if node.type != "call":
            continue
        parts = callee_parts(node, source)
        if parts is None:
            continue
        callee, name, receiver = parts
        calls.append(RawCall(scopes.caller_key(node), callee, name, receiver, line(node)))
    return calls


def _bare_decorator_call(decorator: TSNode, source: bytes, scopes: Scopes) -> RawCall | None:
    """`@logged` or `@a.b` on a function: a call with no parentheses (decision D-11).

    Python runs `logged(f)` when the `def` runs. A called decorator (`@deco(1)`) is an
    ordinary call node and is collected by the main loop.
    """
    expression = decorator.named_children[0] if decorator.named_child_count else None
    if expression is None or expression.type not in ("identifier", "attribute"):
        return None
    function_key = scopes.decorated_function(decorator)
    if function_key is None:
        return None
    callee = one_line(expression, source)
    receiver, _, name = callee.rpartition(".")
    return RawCall(function_key, callee, name, receiver or None, line(decorator))
