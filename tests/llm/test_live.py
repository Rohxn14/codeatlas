"""Real round trips, one per provider. Run with `pytest -m live tests/llm`."""

import pytest

from codeatlas.llm.client import LLMClient
from codeatlas.llm.config import LLMConfig
from codeatlas.llm.types import Message, ToolSpec

pytestmark = pytest.mark.live

WEATHER = ToolSpec(
    "get_weather",
    "Get the weather for a city",
    {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
)


@pytest.mark.parametrize("provider", ["groq", "gemini"])
def test_round_trip(provider, tmp_path):
    config = LLMConfig(providers=(provider,), cache="off", data_dir=str(tmp_path))
    client = LLMClient.from_config(config)
    reply = client.chat([Message("user", "Reply with the single word: pong")], max_tokens=200)
    assert reply.provider == provider
    assert "pong" in reply.text.lower()
    tool_reply = client.chat(
        [Message("user", "What is the weather in Paris? Use the tool.")], tools=[WEATHER]
    )
    assert tool_reply.tool_calls and tool_reply.tool_calls[0].name == "get_weather"
