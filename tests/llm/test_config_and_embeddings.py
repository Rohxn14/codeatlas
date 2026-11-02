"""`[llm]` config with environment overrides, and the cached embedding client."""

import numpy as np
import pytest

from codeatlas.llm.cache import LLMCache
from codeatlas.llm.config import LLMConfig, load_llm_config
from codeatlas.llm.embeddings import EmbeddingClient


def test_defaults_without_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = load_llm_config(environ={})
    assert config == LLMConfig()
    assert config.cache_path.as_posix() == ".codeatlas/llm_cache.sqlite"


def test_toml_then_env(tmp_path):
    path = tmp_path / "codeatlas.toml"
    path.write_text(
        '[paths]\ndata_dir = "work"\n'
        '[llm]\nproviders = ["gemini"]\ngemini_model = "gemini-3.9-flash"\ncache = "off"\n',
        encoding="utf-8",
    )
    config = load_llm_config(path, environ={})
    assert config.providers == ("gemini",)
    assert config.gemini_model == "gemini-3.9-flash"
    assert config.usage_log_path.as_posix() == "work/llm_usage.jsonl"
    env = {"CODEATLAS_LLM_CACHE": "replay_only", "CODEATLAS_LLM_PROVIDERS": "groq, gemini",
           "CODEATLAS_LLM_TIMEOUT": "5"}
    config = load_llm_config(path, environ=env)
    assert config.cache == "replay_only"
    assert config.providers == ("groq", "gemini")
    assert config.timeout_seconds == 5.0


@pytest.mark.parametrize("env", [{"CODEATLAS_LLM_CACHE": "sometimes"},
                                 {"CODEATLAS_LLM_PROVIDERS": "openai"}])
def test_bad_values_raise(tmp_path, monkeypatch, env):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        load_llm_config(environ=env)


class FakeEmbedder:
    """Stands in for fastembed: a fixed vector per text, and a record of batches."""

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def __call__(self, batch: list[str]):
        self.batches.append(batch)
        return [np.array([len(t), 1.0, 0.0], dtype=np.float64) for t in batch]


def test_embed_normalises_batches_and_caches(tmp_path):
    fake = FakeEmbedder()
    cache = LLMCache(tmp_path / "c.sqlite")
    client = EmbeddingClient("test-model", cache, batch_size=2, embedder=fake)
    vectors = client.embed(["a", "bbb", "cc"])
    assert vectors.dtype == np.float32 and vectors.shape == (3, 3)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    assert fake.batches == [["a", "bbb"], ["cc"]]
    again = client.embed(["cc", "dddd", "a"])
    assert fake.batches[-1] == ["dddd"]  # only the new text is embedded
    assert np.allclose(again[0], vectors[2]) and np.allclose(again[2], vectors[0])


def test_embed_cache_is_per_model(tmp_path):
    cache = LLMCache(tmp_path / "c.sqlite")
    first, second = FakeEmbedder(), FakeEmbedder()
    EmbeddingClient("m1", cache, embedder=first).embed(["x"])
    EmbeddingClient("m2", cache, embedder=second).embed(["x"])
    assert second.batches == [["x"]]


def test_embed_empty_and_duplicates():
    fake = FakeEmbedder()
    client = EmbeddingClient("m", None, embedder=fake)
    assert client.embed([]).shape == (0, 0)
    assert client.embed(["x", "x"]).shape == (2, 3)
    assert fake.batches == [["x"]]


def test_thinking_settings_default_low_and_read_the_environment():
    from codeatlas.llm.config import LLMConfig, apply_env

    config = LLMConfig()
    assert (config.gemini_thinking_level, config.groq_reasoning_effort) == ("low", "low")
    assert config.timeout_seconds == 30.0
    changed = apply_env(config, {"CODEATLAS_GEMINI_THINKING": "minimal",
                                 "CODEATLAS_GROQ_REASONING": "high"})
    assert (changed.gemini_thinking_level, changed.groq_reasoning_effort) == ("minimal", "high")


def test_unknown_thinking_level_is_rejected():
    import pytest

    from codeatlas.llm.config import llm_config_from_dict

    with pytest.raises(ValueError, match="gemini_thinking_level"):
        llm_config_from_dict({"gemini_thinking_level": "max"})
