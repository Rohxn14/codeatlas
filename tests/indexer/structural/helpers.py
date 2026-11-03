"""Shared helpers: parse snippets with the real adapters and build a tiny in-memory index."""

from __future__ import annotations

from codeatlas.indexer.registry import Registry
from codeatlas.models import (
    Node,
    NodeKind,
    ParseResult,
    Span,
    make_key,
    make_node_id,
)

SNAPSHOT = "demo@000000000000"
_REGISTRY = Registry(deep={})


def parse(path: str, source: str) -> ParseResult:
    adapter = _REGISTRY.adapter_for(_language(path))
    return adapter.parse(path, source.encode(), SNAPSHOT)


def _language(path: str) -> str:
    return {
        ".java": "java", ".go": "go", ".rb": "ruby", ".py": "python", ".rs": "rust",
        ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
    }[
        "." + path.rsplit(".", 1)[-1]
    ]


class FakeIndex:
    """Just enough of SymbolIndex for profiles: look up Package nodes by key."""

    def __init__(self, packages: dict[str, dict[str, object]] | None = None) -> None:
        self.nodes: dict[str, Node] = {}
        for key, attrs in (packages or {}).items():
            self.nodes[key] = Node(
                make_node_id(SNAPSHOT, key), key, SNAPSHOT, NodeKind.PACKAGE, "go",
                str(attrs.get("module_path", "")), "", "go.mod", Span(1, 1), attrs=attrs,
            )

    def by_key(self, key: str) -> Node | None:
        return self.nodes.get(key)

    def by_name(self, name: str, language: str | None = None) -> list[Node]:
        return []

    def module_for_path(self, path: str) -> Node | None:
        return None

    def members(self, class_key: str) -> list[Node]:
        return []

    def files(self) -> list:
        return []


def go_module(result: ParseResult, package_key: str) -> ParseResult:
    """Give a parsed Go file the `package_key` the pipeline would have set."""
    from dataclasses import replace

    module = result.nodes[0]
    attrs = {**module.attrs, "package_key": package_key}
    return replace(result, nodes=(replace(module, attrs=attrs), *result.nodes[1:]))


GO_PACKAGE_KEY = make_key("go.mod", "package:example.com/shop")
GO_INDEX_ATTRS = {GO_PACKAGE_KEY: {"module_path": "example.com/shop", "root": ""}}
