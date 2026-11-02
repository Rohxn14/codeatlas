"""Model-family fallback rule and the canonical cache key."""

from codeatlas.llm.cache import cache_key, canonical_json
from codeatlas.llm.providers.base import ModelInfo, choose_model, model_family
from codeatlas.llm.types import Message, ToolCall, ToolSpec

# The key of [user: "hi"], temperature 0, no tools, namespace "default". If this changes,
# every recorded answer in every cache stops replaying.
PINNED_KEY = "81d9f1846978062a09eb93b1266598551f3af33a1e0afea60053d24dd7e78bd0"


def test_family_blanks_versions_but_keeps_sizes():
    assert model_family("gemini-3.8-flash") == "gemini-#-flash"
    assert model_family("openai/gpt-oss-20b") == "openai/gpt-oss-20b"
    assert model_family("openai/gpt-oss-20b") != model_family("openai/gpt-oss-120b")
    assert model_family("llama-3.1-8b-instant") == "llama-#-8b-instant"
    assert model_family("gemini-3.8-flash-lite") != model_family("gemini-3.8-flash")


def test_choose_model_stays_in_the_same_size():
    listed = [ModelInfo("llama-3.3-8b-instant"), ModelInfo("llama-3.3-70b-instant")]
    assert choose_model("llama-3.1-8b-instant", listed) == "llama-3.3-8b-instant"


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
    assert key == PINNED_KEY


def test_key_changes_with_tool_schemas_and_tool_call_ids():
    tool = ToolSpec("f", "find code", {"type": "object", "properties": {"q": {}}})
    base = cache_key([Message("user", "hi")], [tool], 0.0, None, "ns")
    other_schema = ToolSpec("f", "find code", {"type": "object", "properties": {"p": {}}})
    other_text = ToolSpec("f", "find tests", tool.parameters)
    assert base != cache_key([Message("user", "hi")], [other_schema], 0.0, None, "ns")
    assert base != cache_key([Message("user", "hi")], [other_text], 0.0, None, "ns")
    one = [Message("tool", "r", tool_call_id="a")]
    two = [Message("tool", "r", tool_call_id="b")]
    assert cache_key(one, None, 0.0, None, "ns") != cache_key(two, None, 0.0, None, "ns")
