import os
from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
EXPORTS_DIR = DATA_DIR / "exports"
MEDIA_DIR = DATA_DIR / "media"

DATA_DIR.mkdir(exist_ok=True)
EXPORTS_DIR.mkdir(exist_ok=True)
MEDIA_DIR.mkdir(exist_ok=True)


class Settings(BaseSettings):
    google_api_key: str = ""
    db_path: str = str(DATA_DIR / "anki_generator.db")
    gemini_model: str = "gemini-2.5-flash-lite"
    embedding_model: str = "models/text-embedding-004"

    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"


settings = Settings()
