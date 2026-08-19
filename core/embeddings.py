from __future__ import annotations

import difflib
import logging

import numpy as np

from core.config import settings

logger = logging.getLogger(__name__)

_gemini_client = None
_ollama_client = None
_embedding_warned = False


def _get_gemini_client():
    global _gemini_client
    if not settings.google_api_key:
        return None
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=settings.google_api_key)
    return _gemini_client


def _get_ollama_client():
    global _ollama_client
    if _ollama_client is None:
        from openai import OpenAI
        _ollama_client = OpenAI(base_url=settings.ollama_base_url, api_key="ollama")
    return _ollama_client


def get_embedding(text: str) -> np.ndarray | None:
    """Get embedding vector using the configured provider."""
    global _embedding_warned
    if not text.strip():
        return None

    try:
        if settings.llm_provider == "gemini":
            client = _get_gemini_client()
            if not client:
                return None
            result = client.models.embed_content(
                model=settings.embedding_model,
                contents=text,
            )
            return np.array(result.embeddings[0].values, dtype=np.float32)
        else:
            client = _get_ollama_client()
            result = client.embeddings.create(
                model=settings.ollama_embedding_model,
                input=text,
            )
            return np.array(result.data[0].embedding, dtype=np.float32)
    except Exception as e:
        if not _embedding_warned:
            logger.warning("Embeddings unavailable — using fuzzy matching only: %s", e)
            _embedding_warned = True
        return None


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def fuzzy_match(text_a: str, text_b: str, threshold: float = 0.85) -> bool:
    a = text_a.lower().strip()
    b = text_b.lower().strip()
    for article in ["the ", "a ", "an ", "la ", "le ", "el "]:
        if a.startswith(article):
            a = a[len(article):]
        if b.startswith(article):
            b = b[len(article):]
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold


def is_duplicate(
    new_q: str,
    existing_cards: list[dict],
    existing_embeddings: list[np.ndarray | None],
    new_embedding: np.ndarray | None = None,
    fuzzy_threshold: float = 0.85,
    semantic_threshold: float = 0.90,
) -> tuple[bool, str]:
    """Two-tier duplicate detection. Returns (is_dup, reason)."""
    # Tier 1: Fuzzy question match
    for existing in existing_cards:
        eq = existing.get("Question", "")
        if new_q and eq and fuzzy_match(new_q, eq, fuzzy_threshold):
            return True, f"Fuzzy match: '{eq[:60]}'"

    # Tier 2: Semantic similarity via embeddings
    if new_embedding is not None:
        for i, emb in enumerate(existing_embeddings):
            if emb is not None:
                try:
                    sim = cosine_similarity(new_embedding, emb)
                except ValueError:
                    continue  # dimension mismatch (e.g. switched embedding model)
                if sim >= semantic_threshold:
                    eq = existing_cards[i].get("Question", "")
                    return True, f"Semantic match (sim={sim:.3f}): '{eq[:60]}'"

    return False, ""
