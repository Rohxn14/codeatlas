"""The deep-tier Python adapter: one file in, one ParseResult out.

Each concern lives in its own module (definitions, testing, imports, calls, routes,
http_calls); this one parses the file once and hands the same tree to each of them.
It never looks at other files: names stay as written, for the resolver (T06) and the
HTTP linker (T11) to connect.
"""

from __future__ import annotations

from dataclasses import replace

import tree_sitter_python
from tree_sitter import Language, Parser

from codeatlas.indexer.discover import extensions_for
from codeatlas.indexer.generic.adapter import module_node, syntax_errors
from codeatlas.indexer.languages.python.calls import collect_calls
from codeatlas.indexer.languages.python.definitions import (
    PyDefinition,
    Scopes,
    collect_definitions,
    docstring,
)
from codeatlas.indexer.languages.python.http_calls import collect_http_calls
from codeatlas.indexer.languages.python.imports import collect_imports
from codeatlas.indexer.languages.python.routes import collect_routes
from codeatlas.indexer.languages.python.syntax import span
from codeatlas.indexer.languages.python.testing import mark_tests
from codeatlas.models import Node, ParseResult, Tier, make_node_id


class PythonAdapter:
    """Deep-tier adapter for Python, built on the tree-sitter Python grammar."""

    language: str = "python"
    tier: Tier = Tier.DEEP

    def __init__(self) -> None:
        self.extensions = extensions_for(self.language)
        self._parser = Parser(Language(tree_sitter_python.language()))

    def parse(self, path: str, source: bytes, snapshot_id: str) -> ParseResult:
        """Never raises: a failure anywhere still yields the module node and an error."""
        module = module_node(path, self.language, source, snapshot_id)
        try:
            return self._parse(path, source, snapshot_id, module)
        except Exception as exc:  # defensive: an adapter bug must not stop indexing
            return ParseResult(
                path, self.language, self.tier, (module,), errors=(f"adapter failed: {exc}",)
            )

    def _parse(self, path: str, source: bytes, snapshot_id: str, module: Node) -> ParseResult:
        root = self._parser.parse(source).root_node
        module = replace(module, docstring=docstring(root, source))
        definitions = collect_definitions(root, source, path)
        mark_tests(definitions, path)
        scopes = Scopes(definitions, module.key)
        imports = collect_imports(root, source, module.key)
        return ParseResult(
            path=path,
            language=self.language,
            tier=self.tier,
            nodes=(module, *(self._node(d, path, source, snapshot_id) for d in definitions)),
            imports=tuple(imports),
            calls=tuple(collect_calls(root, source, scopes)),
            routes=tuple(collect_routes(root, source, definitions, imports)),
            http_calls=tuple(collect_http_calls(root, source, scopes)),
            errors=syntax_errors(root),
        )

    def _node(self, definition: PyDefinition, path: str, source: bytes, snapshot_id: str) -> Node:
        """The span covers decorators too, so a diff that only edits one still hits it."""
        return Node(
            id=make_node_id(snapshot_id, definition.key),
            key=definition.key,
            snapshot_id=snapshot_id,
            kind=definition.kind,
            language=self.language,
            name=definition.name,
            qualname=definition.qualname,
            path=path,
            span=span(definition.outer),
            signature=definition.signature,
            docstring=docstring(definition.node.child_by_field_name("body"), source),
            owner_key=definition.owner_key,
            attrs=definition.attrs,
        )
