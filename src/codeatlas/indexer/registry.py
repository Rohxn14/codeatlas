"""Registry: picks the adapter for each language, deepest tier first.

Order of precedence for a language:

1. a deep adapter listed in `DEEP_ADAPTERS` (T01 adds Python, T02 TypeScript/JavaScript);
2. the structural tags adapter, when a grammar in `GRAMMARS` is installed and its tags
   query compiles;
3. the text adapter, which emits only the module node and records why.

Every fallback keeps its reason, so a language is never downgraded silently.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Language

from codeatlas.indexer.adapter import LanguageAdapter
from codeatlas.indexer.discover import extensions_for
from codeatlas.indexer.generic.adapter import TagsAdapter, TextAdapter
from codeatlas.models import Tier

# Deep adapters, by grammar name: "module.path:ClassName", imported on first use.
# The class is constructed with no arguments. Example entry (T01):
#   "python": "codeatlas.indexer.languages.python.adapter:PythonAdapter",
DEEP_ADAPTERS: dict[str, str] = {}

_VENDORED_QUERIES = Path(__file__).parent / "queries"


@dataclass(frozen=True, slots=True)
class GrammarSpec:
    """Where to find one tree-sitter grammar and its tags query."""

    language: str
    module: str
    distribution: str
    function: str = "language"
    # Languages whose tags query comes first; tree-sitter-typescript's own tags.scm
    # only adds TypeScript-specific patterns on top of JavaScript's.
    inherits: tuple[str, ...] = ()


GRAMMARS: dict[str, GrammarSpec] = {
    spec.language: spec
    for spec in (
        GrammarSpec("python", "tree_sitter_python", "tree-sitter-python"),
        GrammarSpec(
            "typescript",
            "tree_sitter_typescript",
            "tree-sitter-typescript",
            "language_typescript",
            ("javascript",),
        ),
        GrammarSpec(
            "tsx", "tree_sitter_typescript", "tree-sitter-typescript", "language_tsx",
            ("javascript",),
        ),
        GrammarSpec("javascript", "tree_sitter_javascript", "tree-sitter-javascript"),
        GrammarSpec("go", "tree_sitter_go", "tree-sitter-go"),
        GrammarSpec("java", "tree_sitter_java", "tree-sitter-java"),
        GrammarSpec("rust", "tree_sitter_rust", "tree-sitter-rust"),
        GrammarSpec("c_sharp", "tree_sitter_c_sharp", "tree-sitter-c-sharp"),
        GrammarSpec("php", "tree_sitter_php", "tree-sitter-php", "language_php"),
        GrammarSpec("ruby", "tree_sitter_ruby", "tree-sitter-ruby"),
        GrammarSpec("c", "tree_sitter_c", "tree-sitter-c"),
        GrammarSpec("cpp", "tree_sitter_cpp", "tree-sitter-cpp"),
        GrammarSpec("scala", "tree_sitter_scala", "tree-sitter-scala"),
        GrammarSpec("lua", "tree_sitter_lua", "tree-sitter-lua"),
        GrammarSpec("swift", "tree_sitter_swift", "tree-sitter-swift"),
        GrammarSpec("elixir", "tree_sitter_elixir", "tree-sitter-elixir"),
    )
}


class GrammarUnavailable(Exception):
    """A grammar or its tags query could not be loaded; the message is the reason."""


class Registry:
    """Builds and caches one adapter per language."""

    def __init__(
        self,
        deep: dict[str, str] | None = None,
        grammars: dict[str, GrammarSpec] | None = None,
    ) -> None:
        self._deep = DEEP_ADAPTERS if deep is None else deep
        self._grammars = GRAMMARS if grammars is None else grammars
        self._adapters: dict[str, LanguageAdapter] = {}
        self._reasons: dict[str, str] = {}

    def adapter_for(self, language: str) -> LanguageAdapter:
        """The deepest working adapter for `language`; never raises."""
        if language not in self._adapters:
            self._adapters[language] = self._build(language)
        return self._adapters[language]

    def tier_for(self, language: str) -> Tier:
        return self.adapter_for(language).tier

    def fallback_reasons(self) -> dict[str, str]:
        """Why each language built so far got a shallower tier than it asked for."""
        return dict(self._reasons)

    def _build(self, language: str) -> LanguageAdapter:
        reasons: list[str] = []
        if language in self._deep:
            try:
                return _load_deep(self._deep[language])
            except Exception as exc:  # a broken deep adapter must not stop indexing
                reasons.append(f"deep adapter failed to load: {exc}")
        spec = self._grammars.get(language)
        if spec is not None:
            try:
                grammar = load_grammar(spec)
                query = load_tags_query(spec, self._grammars)
                adapter = TagsAdapter(language, grammar, query, extensions_for(language))
                self._remember(language, reasons)
                return adapter
            except GrammarUnavailable as exc:
                reasons.append(str(exc))
            except Exception as exc:  # e.g. a tags query that does not compile
                reasons.append(f"tags adapter for {language} failed: {exc}")
        else:
            reasons.append(f"no tree-sitter grammar configured for {language!r}")
        self._remember(language, reasons)
        return TextAdapter(language, "; ".join(reasons), extensions_for(language))

    def _remember(self, language: str, reasons: list[str]) -> None:
        if reasons:
            self._reasons[language] = "; ".join(reasons)


def _load_deep(target: str) -> LanguageAdapter:
    module_name, _, class_name = target.partition(":")
    adapter = getattr(importlib.import_module(module_name), class_name)()
    if not isinstance(adapter, LanguageAdapter):
        raise TypeError(f"{target} does not implement LanguageAdapter")
    return adapter


def load_grammar(spec: GrammarSpec) -> Language:
    try:
        module = importlib.import_module(spec.module)
        return Language(getattr(module, spec.function)())
    except Exception as exc:
        raise GrammarUnavailable(f"grammar {spec.distribution} not usable: {exc}") from exc


def load_tags_query(spec: GrammarSpec, grammars: dict[str, GrammarSpec]) -> str:
    """The tags query for `spec`: inherited languages first, then its own, then extras.

    `queries/<language>/extra.scm` holds CodeAtlas's own additions for gaps in an
    upstream query; they are appended, never replacing what upstream ships.
    """
    parts = [_own_tags_query(grammars[name]) for name in spec.inherits]
    parts.append(_own_tags_query(spec))
    extra = _VENDORED_QUERIES / spec.language / "extra.scm"
    if extra.is_file():
        parts.append(extra.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _own_tags_query(spec: GrammarSpec) -> str:
    """Shipped query first (a module constant, then a file in the wheel), then vendored."""
    try:
        module = importlib.import_module(spec.module)
    except ImportError as exc:
        raise GrammarUnavailable(f"grammar {spec.distribution} not installed") from exc
    shipped = getattr(module, "TAGS_QUERY", None)
    if isinstance(shipped, str) and shipped.strip():
        return shipped
    try:
        files = importlib.metadata.files(spec.distribution) or []
    except importlib.metadata.PackageNotFoundError:
        files = []
    for file in files:
        if str(file).replace("\\", "/").endswith("queries/tags.scm"):
            return Path(str(file.locate())).read_text(encoding="utf-8")
    vendored = _VENDORED_QUERIES / spec.language / "tags.scm"
    if vendored.is_file():
        return vendored.read_text(encoding="utf-8")
    raise GrammarUnavailable(f"no tags query for {spec.language}")
