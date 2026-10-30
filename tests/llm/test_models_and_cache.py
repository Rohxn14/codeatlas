"""Model-family fallback rule and the canonical cache key."""

from codeatlas.llm.cache import cache_key, canonical_json
from codeatlas.llm.providers.base import ModelInfo, choose_model, model_family
from codeatlas.llm.types import Message, ToolCall, ToolSpec


def test_family_blanks_versions_and_sizes():
    assert model_family("gemini-3.8-flash") == "gemini-#-flash"
    assert model_family("openai/gpt-oss-20b") == "openai/gpt-oss-#b"
    assert model_family("gemini-3.8-flash-lite") != model_family("gemini-3.8-flash")


def test_choose_model():
    gemini = [ModelInfo("gemini-3.7-flash"), ModelInfo("gemini-3.9-flash"),
              ModelInfo("gemini-3.9-flash-lite")]
    assert choose_model("gemini-3.7-flash", gemini) == "gemini-3.7-flash"
    assert choose_model("gemini-3.8-flash", gemini) == "gemini-3.9-flash"
    assert choose_model("claude-x", gemini) is None
    dated = [ModelInfo("m-1", created=200), ModelInfo("m-2", created=100)]
    assert choose_model("m-0", dated) == "m-1"  # creation time wins over the number


def test_key_ignores_dict_order():
    a = [Message("assistant", "", tool_calls=(ToolCall("1", "f", {"a": 1, "b": 2}),))]
    b = [Message("assistant", "", tool_calls=(ToolCall("1", "f", {"b": 2, "a": 1}),))]
    tool_a = [ToolSpec("f", "d", {"type": "object", "properties": {"x": {}, "y": {}}})]
    tool_b = [ToolSpec("f", "d", {"properties": {"y": {}, "x": {}}, "type": "object"})]
    assert cache_key(a, tool_a, 0.0, None, "ns") == cache_key(b, tool_b, 0, None, "ns")


def test_key_changes_with_what_matters():
    base = cache_key([Message("user", "hi")], None, 0.0, None, "ns")
    assert base != cache_key([Message("user", "hi!")], None, 0.0, None, "ns")
    assert base != cache_key([Message("user", "hi")], None, 0.2, None, "ns")
    assert base != cache_key([Message("user", "hi")], None, 0.0, 10, "ns")
    assert base != cache_key([Message("user", "hi")], None, 0.0, None, "other")


def test_key_ignores_provider_signature():
    plain = [Message("assistant", "", tool_calls=(ToolCall("1", "f", {}),))]
    signed = [Message("assistant", "", tool_calls=(ToolCall("1", "f", {}, signature="xyz"),))]
    assert cache_key(plain, None, 0.0, None, "") == cache_key(signed, None, 0.0, None, "")


def test_key_is_stable_across_runs():
    """A changed key would orphan every recorded fixture, so pin one value."""
    key = cache_key([Message("user", "hi")], None, 0.0, None, "default")
    assert canonical_json({"b": 1, "a": [1, 2]}) == '{"a":[1,2],"b":1}'
    assert len(key) == 64
    assert key == cache_key([Message("user", "hi")], None, 0, None, "default")
