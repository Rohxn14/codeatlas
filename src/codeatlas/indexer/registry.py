"""The registry picks one adapter per language: deep if one is registered, else tags, else text.

Deep adapters (T01 for Python, T02 for TypeScript and JavaScript) each add one entry to
`DEEP_ADAPTERS`. A language with a grammar in `GRAMMARS` gets the structural tags adapter;
anything else, or a grammar whose package fails to load, gets the text tier with the reason.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from codeatlas.indexer.adapter import LanguageAdapter
from codeatlas.indexer.discover import extensions_for
from codeatlas.indexer.generic import TagsAdapter, TextAdapter
from codeatlas.indexer.generic.grammars import GRAMMARS
from codeatlas.models import Tier

# Grammar name -> factory for a deep adapter. Deep adapters take precedence over tags.
DEEP_ADAPTERS: dict[str, Callable[[], LanguageAdapter]] = {}


class Registry:
    """Builds each language's adapter once, on first use, and remembers it."""

    def __init__(
        self, deep: dict[str, Callable[[], LanguageAdapter]] | None = None
    ) -> None:
        self._deep = dict(DEEP_ADAPTERS if deep is None else deep)
        self._adapters: dict[str, LanguageAdapter] = {}

    def adapter_for(self, language: str) -> LanguageAdapter:
        """The adapter for a grammar name or text language; never raises."""
        if language not in self._adapters:
            self._adapters[language] = self._build(language)
        return self._adapters[language]

    def tier_for(self, language: str) -> Tier:
        return self.adapter_for(language).tier

    def _build(self, language: str) -> LanguageAdapter:
        extensions = extensions_for(language)
        factory = self._deep.get(language)
        if factory is not None:
            return factory()
        spec = GRAMMARS.get(language)
        if spec is None:
            return TextAdapter(language, extensions)
        try:
            return TagsAdapter(spec, extensions)
        except Exception as exc:  # a missing or incompatible grammar package
            reason = f"{language} grammar unavailable, indexed as text: {exc!r}"
            return TextAdapter(language, extensions, reason=reason)


@lru_cache(maxsize=1)
def default_registry() -> Registry:
    """One shared registry, so each grammar and query is compiled once per process."""
    return Registry()
