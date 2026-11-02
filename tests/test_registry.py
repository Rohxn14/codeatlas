import pytest
from tree_sitter import Language, Query

from codeatlas.indexer.generic.adapter import TagsAdapter, TextAdapter
from codeatlas.indexer.registry import (
    GRAMMARS,
    GrammarSpec,
    Registry,
    load_grammar,
    load_tags_query,
)
from codeatlas.models import Tier


@pytest.mark.parametrize("language", sorted(GRAMMARS))
def test_every_grammar_loads_with_a_compiling_tags_query(language: str) -> None:
    spec = GRAMMARS[language]
    grammar = load_grammar(spec)
    assert isinstance(grammar, Language)
    Query(grammar, load_tags_query(spec, GRAMMARS))
    adapter = Registry(deep={}).adapter_for(language)
    assert isinstance(adapter, TagsAdapter)
    assert adapter.tier is Tier.STRUCTURAL


def test_required_languages_are_structural() -> None:
    registry = Registry(deep={})  # the structural tier itself, without deep adapters
    for language in ("python", "typescript", "tsx", "javascript", "go", "java", "rust",
                     "c_sharp", "php"):
        assert registry.tier_for(language) is Tier.STRUCTURAL, language
    assert registry.fallback_reasons() == {}


def test_deep_adapter_takes_precedence() -> None:
    registry = Registry(deep={"go": "fakes.deep:FakeDeepAdapter"})
    assert registry.tier_for("go") is Tier.DEEP
    assert registry.tier_for("java") is Tier.STRUCTURAL


def test_broken_deep_adapter_falls_back_with_reason() -> None:
    registry = Registry(deep={"go": "fakes.deep:NotAnAdapter"})
    assert registry.tier_for("go") is Tier.STRUCTURAL
    assert "deep adapter failed" in registry.fallback_reasons()["go"]


def test_missing_grammar_falls_back_to_text_with_reason() -> None:
    grammars = {"nope": GrammarSpec("nope", "tree_sitter_does_not_exist", "tree-sitter-nope")}
    registry = Registry(grammars=grammars)
    adapter = registry.adapter_for("nope")
    assert isinstance(adapter, TextAdapter)
    assert "not usable" in registry.fallback_reasons()["nope"]


def test_unknown_language_is_text() -> None:
    registry = Registry()
    assert registry.tier_for("kotlin") is Tier.TEXT
    assert "kotlin" in registry.fallback_reasons()


def test_typescript_inherits_javascript_patterns() -> None:
    adapter = Registry(deep={}).adapter_for("typescript")
    result = adapter.parse(
        "a.ts",
        b"interface Repo { save(): void }\nclass Svc { run() { helper(); } }\n",
        "s@1",
    )
    kinds = {n.qualname: str(n.kind) for n in result.nodes}
    assert kinds["Repo"] == "interface"  # from TypeScript's own tags.scm
    assert kinds["Svc.run"] == "function"  # from JavaScript's
    assert [c.caller_key for c in result.calls] == ["a.ts::Svc.run"]
