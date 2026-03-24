from __future__ import annotations

import difflib
import logging

import numpy as np
from google import genai

from core.config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> genai.Client | None:
    global _client
    if not settings.google_api_key:
        return None
    if _client is None:
        _client = genai.Client(api_key=settings.google_api_key)
    return _client


def get_embedding(text: str) -> np.ndarray | None:
    """Get embedding vector for text using Gemini embedding API."""
    client = _get_client()
    if not client or not text.strip():
        return None

    try:
        result = client.models.embed_content(
            model=settings.embedding_model,
            contents=text,
        )
        return np.array(result.embeddings[0].values, dtype=np.float32)
    except Exception as e:
        logger.warning("Embedding generation failed: %s", e)
        return None


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def fuzzy_match(text_a: str, text_b: str, threshold: float = 0.85) -> bool:
    """Check if two strings are fuzzy matches (for title/artist dedup)."""
    a = text_a.lower().strip()
    b = text_b.lower().strip()
    for article in ["the ", "a ", "an ", "la ", "le ", "el "]:
        if a.startswith(article):
            a = a[len(article):]
        if b.startswith(article):
            b = b[len(article):]
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold


def card_text_for_embedding(fields: dict) -> str:
    """Build a text representation of a card for embedding."""
    parts = []
    for key, value in fields.items():
        if value and isinstance(value, str) and len(value.strip()) > 0:
            parts.append(f"{key}: {value}")
    return " | ".join(parts)


def is_duplicate(
    new_fields: dict,
    existing_cards: list[dict],
    existing_embeddings: list[np.ndarray | None],
    new_embedding: np.ndarray | None = None,
    fuzzy_threshold: float = 0.85,
    semantic_threshold: float = 0.90,
) -> tuple[bool, str]:
    """
    Two-tier duplicate detection.
    Returns (is_dup, reason).
    """
    new_title = new_fields.get("Title", "").strip()
    new_artist = new_fields.get("Artist", "").strip()

    # Tier 1: Fuzzy title + artist match
    for existing in existing_cards:
        ex_title = existing.get("Title", "").strip()
        ex_artist = existing.get("Artist", "").strip()

        if new_title and ex_title and fuzzy_match(new_title, ex_title, fuzzy_threshold):
            if not new_artist or not ex_artist or fuzzy_match(new_artist, ex_artist, fuzzy_threshold):
                return True, f"Fuzzy match: '{ex_title}' by '{ex_artist}'"

    # Tier 2: Semantic similarity via embeddings
    if new_embedding is not None:
        for i, emb in enumerate(existing_embeddings):
            if emb is not None:
                sim = cosine_similarity(new_embedding, emb)
                if sim >= semantic_threshold:
                    ex = existing_cards[i]
                    return True, f"Semantic match (sim={sim:.3f}): '{ex.get('Title', '')}'"

    return False, ""
