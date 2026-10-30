"""Deep-tier adapters for TypeScript, TSX and JavaScript, sharing one implementation.

The three grammars name almost every node the same way (TypeScript's grammar extends
JavaScript's), so one extractor serves all three; each class only picks its grammar.
Each concern lives in its own module: symbols, imports, calls, routes and HTTP calls.
"""

from __future__ import annotations

from tree_sitter import Language, Parser

from codeatlas.indexer.discover import extensions_for
from codeatlas.indexer.generic.adapter import module_node, syntax_errors
from codeatlas.indexer.languages.typescript.calls import extract_calls
from codeatlas.indexer.languages.typescript.http import axios_clients, extract_http_calls
from codeatlas.indexer.languages.typescript.imports import extract_imports
from codeatlas.indexer.languages.typescript.routes import extract_routes
from codeatlas.indexer.languages.typescript.symbols import Symbols
from codeatlas.models import ParseResult, Tier


class _EcmaScriptAdapter:
    """Shared parse step; subclasses set `language` and supply the grammar."""

    language: str
    tier: Tier = Tier.DEEP

    def __init__(self) -> None:
        self.extensions = extensions_for(self.language)
        self._parser = Parser(self._grammar())

    @staticmethod
    def _grammar() -> Language:
        raise NotImplementedError

    def parse(self, path: str, source: bytes, snapshot_id: str) -> ParseResult:
        """Never raises: a failure anywhere still yields the module node and an error."""
        module = module_node(path, self.language, source, snapshot_id)
        try:
            tree = self._parser.parse(source)
            root = tree.root_node
            symbols = Symbols(root, source, path)
            clients = axios_clients(root, source)
            return ParseResult(
                path,
                self.language,
                self.tier,
                (module, *symbols.nodes(self.language, snapshot_id)),
                imports=tuple(extract_imports(root, source, symbols.module_key)),
                calls=tuple(extract_calls(root, source, symbols)),
                routes=tuple(extract_routes(root, source, symbols, frozenset(clients))),
                http_calls=tuple(extract_http_calls(root, source, symbols, clients)),
                errors=syntax_errors(root),
            )
        except Exception as exc:  # defensive: an extractor bug must not stop indexing
            return ParseResult(
                path, self.language, self.tier, (module,), errors=(f"adapter failed: {exc}",)
            )


class TypeScriptAdapter(_EcmaScriptAdapter):
    language = "typescript"

    @staticmethod
    def _grammar() -> Language:
        import tree_sitter_typescript

        return Language(tree_sitter_typescript.language_typescript())


class TsxAdapter(_EcmaScriptAdapter):
    language = "tsx"

    @staticmethod
    def _grammar() -> Language:
        import tree_sitter_typescript

        return Language(tree_sitter_typescript.language_tsx())


class JavaScriptAdapter(_EcmaScriptAdapter):
    """JavaScript, JSX, `.mjs` and `.cjs`: the JavaScript grammar parses JSX too."""

    language = "javascript"

    @staticmethod
    def _grammar() -> Language:
        import tree_sitter_javascript

        return Language(tree_sitter_javascript.language())
