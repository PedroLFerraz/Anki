import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root when running from a checkout; the working directory otherwise
# (e.g. inside a container, where the package is installed into site-packages).
_REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = _REPO_ROOT if (_REPO_ROOT / "pyproject.toml").exists() else Path.cwd()


def _default_collection() -> str:
    """Anki desktop's collection, when exactly one profile exists."""
    root = Path(os.environ.get("APPDATA", Path.home() / ".local/share")) / "Anki2"
    found = sorted(root.glob("*/collection.anki2")) if root.exists() else []
    return str(found[0]) if len(found) == 1 else ""


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
        # Similarity scale differs per embedding model, so the duplicate
        # threshold belongs to the model, not to the dedup code.
        "embedding_threshold": 0.90,
        "needs_key": False,
        "notes": "Runs on your machine. No limits, no key, works offline.",
    },
    "groq": {
        "label": "Groq",
        # Verified against console.groq.com/docs/models. Groq retires model IDs
        # fairly often — `python cli.py providers` will surface a 404 as a
        # failed connection check.
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
        "embedding_model": None,
        "needs_key": True,
        "notes": "Fastest, 1000 requests/day. No embeddings endpoint, so those "
                 "fall back to local Ollama.",
    },
    "nvidia": {
        "label": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "meta/llama-3.3-70b-instruct",
        "embedding_model": "nvidia/nv-embedqa-e5-v5",
        "needs_key": True,
        "notes": "Serves both chat and embeddings. Needs a free developer account.",
    },
    "openrouter": {
        "label": "OpenRouter",
        # Verified against https://openrouter.ai/api/v1/models. OpenRouter retires
        # free model ids often, so check there if a request 404s.
        "base_url": "https://openrouter.ai/api/v1",
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
        "embedding_model": "liquid/lfm-2.5-embedding-350m:free",
        # Measured on real card pairs: reworded duplicates 0.92-0.98,
        # same-topic non-duplicates 0.20-0.35, unrelated ~0.00. This model has a
        # far lower floor than nomic, so 0.90 would miss real duplicates.
        "embedding_threshold": 0.60,
        "needs_key": True,
        "notes": "One key for chat and embeddings, both free. ~50 requests/day "
                 "until you have bought $10 of credit, then 1000.",
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

# Used when a model has no measured threshold of its own.
DEFAULT_SEMANTIC_THRESHOLD = 0.90


def provider_names() -> list[str]:
    return sorted(PROVIDERS) + sorted(NATIVE_PROVIDERS)


class PaidModelBlocked(RuntimeError):
    """Raised before a request that would cost money."""


def ensure_free(provider: str, model: str, allow_paid: bool) -> None:
    """Refuse to call a paid OpenRouter model unless explicitly allowed.

    OpenRouter marks zero-cost models with a `:free` suffix, so the check is
    exact there. Other providers don't encode price in the model id, so their
    own free tiers are the only safeguard.
    """
    if allow_paid or provider != "openrouter":
        return
    if not model.endswith(":free"):
        raise PaidModelBlocked(
            f"Refusing to call OpenRouter model {model!r}: it is not a ':free' model "
            "and would be billed. Pick a free model, or set ALLOW_PAID_MODELS=true "
            "in .env if you really mean to spend credit."
        )


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

    # Guard against accidentally billing an OpenRouter key.
    allow_paid_models: bool = False

    # Cosine similarity above which two cards count as duplicates.
    # 0 means "use the embedding model's own default" (see PROVIDERS).
    semantic_threshold: float = 0.0

    # --- pipeline ---
    # Live Anki collection. The pipeline only ever reads a snapshot of it.
    anki_collection_path: str = _default_collection()
    ankigen_profile: str = str(BASE_DIR / "profiles" / "default.yaml")
    data_dir: str = str(BASE_DIR / "data")

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

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
                "threshold": self.semantic_threshold or DEFAULT_SEMANTIC_THRESHOLD,
            }

        preset = PROVIDERS.get(name)
        if not preset or not preset.get("embedding_model"):
            return {"provider": None, "base_url": None, "api_key": "", "model": "",
                    "threshold": DEFAULT_SEMANTIC_THRESHOLD}

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
            "threshold": (self.semantic_threshold
                          or preset.get("embedding_threshold")
                          or DEFAULT_SEMANTIC_THRESHOLD),
        }


settings = Settings()
