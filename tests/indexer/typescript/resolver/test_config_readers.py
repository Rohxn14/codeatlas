"""The tolerant JSON reader, tsconfig rules and package entry points, without a pipeline."""

import pytest

from codeatlas.indexer.languages.typescript.resolver.jsonc import parse_jsonc
from codeatlas.indexer.languages.typescript.resolver.modules import (
    _capture,
    _exports_entry,
    _matching_patterns,
)
from codeatlas.indexer.languages.typescript.resolver.tsconfig import load_rules


def test_jsonc_keeps_comment_lookalikes_inside_strings() -> None:
    text = '{ "a": "http://x/*not a comment*/", /* c */ "b": [1, 2,], // end\n }'
    assert parse_jsonc(text) == {"a": "http://x/*not a comment*/", "b": [1, 2]}


def test_jsonc_still_rejects_real_garbage() -> None:
    with pytest.raises(ValueError):
        parse_jsonc("{ nope")


def test_load_rules_applies_extends_and_reports_broken_configs() -> None:
    files = {
        "a/tsconfig.json": b'{"extends": "../base", "compilerOptions": {"baseUrl": "src"}}',
        "base.json": b'{"compilerOptions": {"paths": {"@x/*": ["x/*"]}}}',
        "b/tsconfig.json": b"{ broken",
    }
    rules, problems = load_rules(["a/tsconfig.json", "b/tsconfig.json"], files.get)
    assert len(rules) == 1
    # baseUrl "src" belongs to a/; the inherited paths are relative to that baseUrl.
    assert (rules[0].directory, rules[0].base_dir, rules[0].paths_dir) == ("a", "a/src", "a/src")
    assert rules[0].mappings == {"@x/*": ["x/*"]}
    assert len(problems) == 1 and problems[0].startswith("b/tsconfig.json")


def test_path_patterns_prefer_exact_then_longest_prefix() -> None:
    mappings = {"@a/*": ["1"], "@a/b/*": ["2"], "exact": ["3"]}
    assert _matching_patterns(mappings, "exact") == ["exact"]
    assert _matching_patterns(mappings, "@a/b/c") == ["@a/b/*", "@a/*"]
    assert _capture("@a/*", "@a/b/c") == "b/c"
    assert _capture("@a/*", "@b/c") is None


def test_package_exports_forms() -> None:
    assert _exports_entry("./i.js", ".") == "./i.js"
    assert _exports_entry({"import": "./i.mjs", "default": "./i.cjs"}, ".") == "./i.mjs"
    assert _exports_entry({".": {"types": "./t.d.ts"}, "./sub": "./s.js"}, "./sub") == "./s.js"
    assert _exports_entry({"./sub": "./s.js"}, ".") is None
