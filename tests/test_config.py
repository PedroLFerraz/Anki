"""Provider resolution (ported from v1) and connection checks."""
from unittest.mock import patch

import pytest

from ankigen import llm
from ankigen.config import PROVIDERS, Settings


def _s(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_ollama_defaults():
    cfg = _s(llm_provider="ollama").resolve_llm()
    assert cfg["base_url"] == "http://localhost:11434/v1" and cfg["needs_key"] is False


def test_preset_used():
    cfg = _s(llm_provider="groq", llm_api_key="k").resolve_llm()
    assert cfg["base_url"] == PROVIDERS["groq"]["base_url"]
    assert cfg["model"] == PROVIDERS["groq"]["model"] and cfg["api_key"] == "k"


def test_overrides_win():
    cfg = _s(llm_provider="groq", llm_base_url="https://x/v1", llm_model="m").resolve_llm()
    assert (cfg["base_url"], cfg["model"]) == ("https://x/v1", "m")


def test_embeddings_fall_back_to_ollama_when_provider_has_none():
    assert _s(llm_provider="groq").resolve_embedding()["provider"] == "ollama"


def test_embeddings_stay_on_provider_that_supports_them():
    assert _s(llm_provider="nvidia").resolve_embedding()["provider"] == "nvidia"


def test_embeddings_none_for_unsupported_explicit_choice():
    assert _s(embedding_provider="groq").resolve_embedding()["provider"] is None


@pytest.fixture
def use(monkeypatch):
    def apply(**kw):
        monkeypatch.setattr("ankigen.llm.settings", _s(**kw))
    return apply


def test_missing_key(use):
    use(llm_provider="groq", llm_api_key="")
    assert "No API key" in llm.check_connection()


def test_ollama_probe_strips_v1_suffix_not_characters(use):
    """v1 used rstrip('/v1'), which mangled ports ending in 1."""
    use(llm_provider="ollama", ollama_base_url="http://host:8001/v1")
    with patch("requests.get") as get:
        assert llm.check_connection() is None
    assert get.call_args[0][0] == "http://host:8001/api/tags"


def test_hosted_probe_sends_bearer_token(use):
    use(llm_provider="groq", llm_api_key="secret")
    with patch("requests.get") as get:
        assert llm.check_connection() is None
    assert get.call_args[1]["headers"] == {"Authorization": "Bearer secret"}
