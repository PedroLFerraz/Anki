import os
from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
EXPORTS_DIR = DATA_DIR / "exports"
MEDIA_DIR = DATA_DIR / "media"

DATA_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)


# Providers that speak the OpenAI chat-completions protocol. Ollama was always
# reached this way, so pointing at a hosted endpoint is a base URL plus a key.
#
# Free-tier limits and model names move constantly — these are starting points,
# not guarantees. Check the provider's own docs before relying on them.
# See https://github.com/mnfst/awesome-free-llm-apis for a maintained list.
PROVIDERS: dict[str, dict] = {
    "ollama": {
        "label": "Ollama (local)",
        "base_url": "http://localhost:11434/v1",
        "model": "phi4-mini",
        "embedding_model": "nomic-embed-text",
        "needs_key": False,
        "notes": "Runs on your machine. No limits, no key, works offline.",
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "embedding_model": None,
        "needs_key": True,
        "notes": "Very fast. No embeddings endpoint.",
    },
    "nvidia": {
        "label": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "meta/llama-3.3-70b-instruct",
        "embedding_model": "nvidia/nv-embedqa-e5-v5",
        "needs_key": True,
        "notes": "The only free preset here that serves both chat and embeddings.",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "embedding_model": None,
        "needs_key": True,
        "notes": "Many free models; per-model daily caps are low.",
    },
    "sambanova": {
        "label": "SambaNova",
        "base_url": "https://api.sambanova.ai/v1",
        "model": "Meta-Llama-3.3-70B-Instruct",
        "embedding_model": None,
        "needs_key": True,
        "notes": "Daily token budget rather than a request cap.",
    },
    "mistral": {
        "label": "Mistral",
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
        "embedding_model": "mistral-embed",
        "needs_key": True,
        "notes": "Free tier is monthly credits.",
    },
}

# Reached through google-genai rather than the OpenAI SDK, so it is handled
# on its own path in agents.py / embeddings.py.
NATIVE_PROVIDERS = {"gemini"}


def provider_names() -> list[str]:
    return sorted(PROVIDERS) + sorted(NATIVE_PROVIDERS)


class Settings(BaseSettings):
    # Which provider generates cards. Any key of PROVIDERS, or "gemini".
    llm_provider: str = "ollama"

    # Per-call overrides. Empty means "take it from the preset".
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""

    # Embeddings are configured separately on purpose: most free chat APIs do
    # not serve embeddings, so the usual setup is a hosted model for generation
    # plus local Ollama for embeddings. Empty means "derive from llm_provider".
    embedding_provider: str = ""
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model_name: str = ""

    # Gemini
    google_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    embedding_model: str = "gemini-embedding-001"

    # Retained so existing .env files and the Ollama defaults keep working.
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "phi4-mini"
    ollama_embedding_model: str = "nomic-embed-text"

    db_path: str = str(DATA_DIR / "anki_generator.db")

    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"

    # ---------- resolution ----------

    def resolve_llm(self) -> dict:
        """Effective chat config: {provider, base_url, api_key, model, needs_key}."""
        name = (self.llm_provider or "ollama").strip().lower()

        if name in NATIVE_PROVIDERS:
            return {
                "provider": name,
                "base_url": None,
                "api_key": self.google_api_key,
                "model": self.gemini_model,
                "needs_key": True,
            }

        preset = PROVIDERS.get(name, PROVIDERS["ollama"])

        # Ollama keeps honouring its dedicated settings so old .env files work.
        if name == "ollama":
            base_url = self.llm_base_url or self.ollama_base_url
            model = self.llm_model or self.ollama_model
        else:
            base_url = self.llm_base_url or preset["base_url"]
            model = self.llm_model or preset["model"]

        return {
            "provider": name,
            "base_url": base_url,
            # Local Ollama ignores the key but the OpenAI SDK demands a non-empty one.
            "api_key": self.llm_api_key or ("ollama" if not preset["needs_key"] else ""),
            "model": model,
            "needs_key": preset["needs_key"],
        }

    def resolve_embedding(self) -> dict:
        """Effective embedding config, or provider=None when unavailable.

        Falls back to local Ollama when the chat provider serves no embeddings,
        which is the common case on free tiers.
        """
        name = (self.embedding_provider or "").strip().lower()

        if not name:
            chat = (self.llm_provider or "ollama").strip().lower()
            if chat in NATIVE_PROVIDERS:
                name = chat
            elif PROVIDERS.get(chat, {}).get("embedding_model"):
                name = chat
            else:
                name = "ollama"

        if name in NATIVE_PROVIDERS:
            return {
                "provider": name,
                "base_url": None,
                "api_key": self.google_api_key,
                "model": self.embedding_model_name or self.embedding_model,
            }

        preset = PROVIDERS.get(name)
        if not preset or not preset.get("embedding_model"):
            return {"provider": None, "base_url": None, "api_key": "", "model": ""}

        if name == "ollama":
            base_url = self.embedding_base_url or self.ollama_base_url
            model = self.embedding_model_name or self.ollama_embedding_model
        else:
            base_url = self.embedding_base_url or preset["base_url"]
            model = self.embedding_model_name or preset["embedding_model"]

        api_key = self.embedding_api_key or (
            self.llm_api_key if name == (self.llm_provider or "").strip().lower() else ""
        )

        return {
            "provider": name,
            "base_url": base_url,
            "api_key": api_key or ("ollama" if not preset["needs_key"] else ""),
            "model": model,
        }


settings = Settings()
