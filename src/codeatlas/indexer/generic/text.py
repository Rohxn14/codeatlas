"""The text tier: a file CodeAtlas cannot parse still becomes a searchable module node."""

from __future__ import annotations

from codeatlas.indexer.generic.tags import module_node
from codeatlas.models import ParseResult, Tier


class TextAdapter:
    """A `LanguageAdapter` that emits only the module node (tier TEXT).

    `reason` says why a language that has a grammar fell back to text (for example, the
    grammar package is not installed); it lands in every result's `errors`, so the gap
    is visible rather than silent.
    """

    tier = Tier.TEXT

    def __init__(
        self, language: str, extensions: tuple[str, ...] = (), reason: str | None = None
    ) -> None:
        self.language = language
        self.extensions = extensions
        self.reason = reason

    def parse(self, path: str, source: bytes, snapshot_id: str) -> ParseResult:
        return ParseResult(
            path=path,
            language=self.language,
            tier=self.tier,
            nodes=(module_node(path, self.language, source, snapshot_id),),
            errors=(self.reason,) if self.reason else (),
        )
