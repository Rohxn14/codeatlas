"""LLM layer: Groq first, Gemini fallback, record and replay cache (T04)."""

from codeatlas.llm.client import LLMClient
from codeatlas.llm.embeddings import EmbeddingClient
from codeatlas.llm.errors import (
    CacheMissError,
    LLMError,
    LLMRequestError,
    LLMTransientError,
    LLMUnavailableError,
)
from codeatlas.llm.types import LLMResponse, Message, ToolCall, ToolSpec

__all__ = [
    "CacheMissError",
    "EmbeddingClient",
    "LLMClient",
    "LLMError",
    "LLMRequestError",
    "LLMResponse",
    "LLMTransientError",
    "LLMUnavailableError",
    "Message",
    "ToolCall",
    "ToolSpec",
]
