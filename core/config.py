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


class Settings(BaseSettings):
    # Provider: "ollama" (default, free local) or "gemini"
    llm_provider: str = "ollama"

    # Gemini settings
    google_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    embedding_model: str = "gemini-embedding-001"

    # Ollama / OpenAI-compatible settings
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "phi4-mini"
    ollama_embedding_model: str = "nomic-embed-text"

    db_path: str = str(DATA_DIR / "anki_generator.db")

    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"


settings = Settings()
