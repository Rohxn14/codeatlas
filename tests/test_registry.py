import pytest

from codeatlas.indexer.adapter import LanguageAdapter
from codeatlas.indexer.generic import TagsAdapter, TextAdapter
from codeatlas.indexer.generic.grammars import GRAMMARS, GrammarSpec
from codeatlas.indexer.registry import DEEP_ADAPTERS, Registry, default_registry
from codeatlas.models import ParseResult, Tier


class FakeDeep:
    language = "go"
    tier = Tier.DEEP
    extensions = (".go",)

    def parse(self, path: str, source: bytes, snapshot_id: str) -> ParseResult:
        raise NotImplementedError


def test_structural_for_every_grammar() -> None:
    registry = Registry(deep={})
    for language in GRAMMARS:
        adapter = registry.adapter_for(language)
        assert isinstance(adapter, TagsAdapter)
        assert registry.tier_for(language) is Tier.STRUCTURAL


def test_extensions_come_from_discovery() -> None:
    assert Registry(deep={}).adapter_for("typescript").extensions == (".cts", ".mts", ".ts")


def test_deep_takes_precedence() -> None:
    registry = Registry(deep={"go": FakeDeep})
    assert isinstance(registry.adapter_for("go"), FakeDeep)
    assert registry.tier_for("go") is Tier.DEEP
    assert registry.tier_for("java") is Tier.STRUCTURAL


def test_unknown_language_is_text() -> None:
    adapter = Registry(deep={}).adapter_for("kotlin")
    assert isinstance(adapter, TextAdapter)
    assert adapter.tier is Tier.TEXT
    assert adapter.extensions == (".kt", ".kts")


def test_missing_grammar_falls_back_to_text_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = GrammarSpec("go", "tree_sitter_not_installed", query_packages=())
    monkeypatch.setitem(GRAMMARS, "go", broken)
    adapter = Registry(deep={}).adapter_for("go")
    assert isinstance(adapter, TextAdapter)
    result = adapter.parse("a.go", b"package a\n", "s@0")
    assert result.tier is Tier.TEXT
    assert "go grammar unavailable" in result.errors[0]


def test_adapters_are_built_once() -> None:
    registry = Registry(deep={})
    assert registry.adapter_for("rust") is registry.adapter_for("rust")


def test_default_registry_is_shared_and_satisfies_protocol() -> None:
    assert default_registry() is default_registry()
    assert isinstance(default_registry().adapter_for("java"), LanguageAdapter)
    assert DEEP_ADAPTERS == {}  # T01 and T02 add the first entries
