"""Every call expression in the file, as written, with the function it runs in."""

from __future__ import annotations

from tree_sitter import Node as TSNode

from codeatlas.indexer.languages.python.definitions import Scopes
from codeatlas.indexer.languages.python.syntax import callee_parts, line, walk
from codeatlas.models import RawCall


def collect_calls(root: TSNode, source: bytes, scopes: Scopes) -> list[RawCall]:
    """Calls in source order: `a().b()` gives `a().b` first, then `a` inside it.

    Calls in lambdas and comprehensions belong to the function around them, since
    neither is a definition with a key of its own.
    """
    calls = []
    for node in walk(root):
        if node.type != "call":
            continue
        parts = callee_parts(node, source)
        if parts is None:
            continue
        callee, name, receiver = parts
        calls.append(RawCall(scopes.caller_key(node), callee, name, receiver, line(node)))
    return calls
