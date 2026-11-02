
import pytest
from ts_samples import SAMPLES, parse_sample

from codeatlas.cli import scan
from codeatlas.config import Config
from codeatlas.indexer.adapter import LanguageAdapter
from codeatlas.indexer.languages.typescript.adapter import (
    JavaScriptAdapter,
    TsxAdapter,
    TypeScriptAdapter,
)
from codeatlas.indexer.registry import Registry
from codeatlas.models import NodeKind, Span, Tier


@pytest.mark.parametrize(
    ("adapter", "language", "extensions"),
    [
        (TypeScriptAdapter(), "typescript", (".ts", ".mts", ".cts")),
        (TsxAdapter(), "tsx", (".tsx",)),
        (JavaScriptAdapter(), "javascript", (".js", ".mjs", ".cjs", ".jsx")),
    ],
)
def test_adapters_fit_the_protocol(
    adapter: LanguageAdapter, language: str, extensions: tuple[str, ...]
) -> None:
    assert isinstance(adapter, LanguageAdapter)
    assert adapter.language == language
    assert adapter.tier is Tier.DEEP
    assert set(adapter.extensions) == set(extensions)


@pytest.mark.parametrize("language", ["typescript", "tsx", "javascript"])
def test_registry_picks_the_deep_adapter(language: str) -> None:
    registry = Registry()
    assert registry.tier_for(language) is Tier.DEEP
    assert registry.adapter_for(language).language == language
    assert language not in registry.fallback_reasons()


def test_module_node_comes_first() -> None:
    result = parse_sample("shapes.ts")
    module = result.nodes[0]
    assert module.kind is NodeKind.MODULE
    assert module.key == "web/shapes.ts::"
    assert module.id == "web@0123456789ab/web/shapes.ts::"
    assert module.span == Span(1, 41)
    assert (result.path, result.language, result.tier) == ("web/shapes.ts", "typescript", Tier.DEEP)


def test_syntax_error_keeps_what_parsed() -> None:
    result = parse_sample("broken.ts")
    assert result.errors == ("syntax error at line 5, column 0",)
    assert [n.key for n in result.nodes] == ["web/broken.ts::", "web/broken.ts::ok"]


@pytest.mark.parametrize("source", [b"", b"\xff\xfe\x00garbage", b"}}}{{{ class ("])
def test_never_raises(source: bytes) -> None:
    result = TypeScriptAdapter().parse("x.ts", source, "s@1")
    assert result.nodes[0].kind is NodeKind.MODULE


def test_scan_reports_the_deep_tier_for_all_three_grammars() -> None:
    report = scan(str(SAMPLES), Config())
    tiers = {row.language: row.tier for row in report.rows}
    assert tiers == {"typescript": "deep", "tsx": "deep", "javascript": "deep"}
    assert sum(row.files_with_errors for row in report.rows) == 1  # broken.ts
