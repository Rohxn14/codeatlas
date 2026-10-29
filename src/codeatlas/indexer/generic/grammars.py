"""Which tree-sitter grammars CodeAtlas knows, and where each one's tags query comes from.

Each grammar ships as its own pip package. Most include `queries/tags.scm`, which we use
as shipped. Where a package has none (C#) it is vendored under `indexer/queries/`, and
where a shipped query misses call sites (C, C++, C#, Rust) a small CodeAtlas `extra.scm` adds them.
"""

from __future__ import annotations

import importlib
import importlib.resources
from dataclasses import dataclass, field

from tree_sitter import Language

from codeatlas.models import NodeKind


@dataclass(frozen=True, slots=True)
class GrammarSpec:
    """How to load one grammar and build its tags query.

    `query_packages` lists packages whose `queries/tags.scm` are joined in order; TypeScript
    lists JavaScript first because upstream TypeScript tags only add to the JavaScript ones.
    `owner_fields` names, per node type, the field holding a method's owner type when the
    method is not written inside its class: Go receivers, Rust `impl` blocks.
    `type_kinds` turns a `@definition.type` into a node kind by the defined type's node type.
    """

    name: str
    module: str
    function: str = "language"
    query_packages: tuple[str, ...] = ()
    vendored: bool = False
    extra: bool = False
    owner_fields: dict[str, str] = field(default_factory=dict)
    type_kinds: dict[str, NodeKind] = field(default_factory=dict)


GRAMMARS: dict[str, GrammarSpec] = {
    spec.name: spec
    for spec in (
        GrammarSpec("python", "tree_sitter_python", query_packages=("tree_sitter_python",)),
        GrammarSpec(
            "javascript", "tree_sitter_javascript", query_packages=("tree_sitter_javascript",)
        ),
        GrammarSpec(
            "typescript",
            "tree_sitter_typescript",
            "language_typescript",
            query_packages=("tree_sitter_javascript", "tree_sitter_typescript"),
        ),
        GrammarSpec(
            "tsx",
            "tree_sitter_typescript",
            "language_tsx",
            query_packages=("tree_sitter_javascript", "tree_sitter_typescript"),
        ),
        GrammarSpec(
            "go",
            "tree_sitter_go",
            query_packages=("tree_sitter_go",),
            owner_fields={"method_declaration": "receiver"},
            type_kinds={"struct_type": NodeKind.CLASS, "interface_type": NodeKind.INTERFACE},
        ),
        GrammarSpec("java", "tree_sitter_java", query_packages=("tree_sitter_java",)),
        GrammarSpec(
            "rust",
            "tree_sitter_rust",
            query_packages=("tree_sitter_rust",),
            extra=True,
            owner_fields={"impl_item": "type"},
        ),
        GrammarSpec("c_sharp", "tree_sitter_c_sharp", vendored=True, extra=True),
        GrammarSpec(
            "php", "tree_sitter_php", "language_php", query_packages=("tree_sitter_php",)
        ),
        GrammarSpec("c", "tree_sitter_c", query_packages=("tree_sitter_c",), extra=True),
        GrammarSpec("cpp", "tree_sitter_cpp", query_packages=("tree_sitter_cpp",), extra=True),
        GrammarSpec("ruby", "tree_sitter_ruby", query_packages=("tree_sitter_ruby",)),
    )
}


def load_language(spec: GrammarSpec) -> Language:
    """Import the grammar package; raises ImportError when it is not installed."""
    module = importlib.import_module(spec.module)
    return Language(getattr(module, spec.function)())


def load_tags_query(spec: GrammarSpec) -> str:
    """The full tags query text for one grammar, from shipped, vendored and extra parts."""
    parts = [
        importlib.resources.files(package).joinpath("queries/tags.scm").read_text("utf-8")
        for package in spec.query_packages
    ]
    own = importlib.resources.files("codeatlas.indexer").joinpath("queries", spec.name)
    if spec.vendored:
        parts.append(own.joinpath("tags.scm").read_text("utf-8"))
    if spec.extra:
        parts.append(own.joinpath("extra.scm").read_text("utf-8"))
    return "\n".join(parts)
