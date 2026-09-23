"""Dedup stage: drop generated cards that repeat something already studied.

Two tiers, ported from v1:
  1. fuzzy — near-identical question wording (cheap, always on)
  2. semantic — embedding similarity, catches rephrasings

A card is compared against its deck's existing notes, cards kept by earlier
runs that haven't been imported into Anki yet, and cards already kept earlier
in this same run.

Embeddings are cached in the warehouse by content hash, so after the first run
only new or edited notes are embedded. Only decks the profile targets are ever
embedded — a 5,000-card language deck that isn't being generated for costs nothing.
"""
from __future__ import annotations

import difflib
import logging
from datetime import date

import numpy as np

from ankigen import llm
from ankigen.config import ensure_free, settings
from ankigen.ingest import content_hash
from ankigen.targeting import in_deck

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 0.85
BATCH = 64
_ARTICLES = ("the ", "a ", "an ", "la ", "le ", "el ", "der ", "die ", "das ")


def fuzzy_ratio(a: str, b: str) -> float:
    a, b = a.lower().strip(), b.lower().strip()
    for art in _ARTICLES:
        a = a.removeprefix(art)
        b = b.removeprefix(art)
    return difflib.SequenceMatcher(None, a, b).ratio()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class Embedder:
    """Embeds text through the configured provider, caching in the warehouse."""

    def __init__(self, wh):
        self.wh = wh
        self.cfg = settings.resolve_embedding()
        self.model = self.cfg["model"] or ""
        self.threshold = self.cfg.get("threshold") or 0.90
        self.available = bool(self.cfg["provider"])
        self.error: str | None = None if self.available else "no embedding provider configured"
        self.embedded = 0

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        ensure_free(self.cfg["provider"], self.model, settings.allow_paid_models)
        if self.cfg["provider"] == "gemini":
            client = llm._get_gemini_client()
            result = client.models.embed_content(model=self.model, contents=texts)
            return [e.values for e in result.embeddings]
        client = llm._get_openai_client(self.cfg["base_url"], self.cfg["api_key"])
        result = client.embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in result.data]

    def vectors(self, items: dict[str, str]) -> dict[str, np.ndarray]:
        """{content_hash: text} -> {content_hash: vector}. Cache first, provider for the rest."""
        if not self.available or not items:
            return {}
        hashes = list(items)
        cached = {
            r["content_hash"]: np.asarray(r["vector"], dtype=np.float32)
            for r in self.wh.query(
                "SELECT content_hash, vector FROM embedding_cache "
                "WHERE model = ? AND content_hash IN (SELECT UNNEST(?))",
                [self.model, hashes],
            )
        }
        missing = [h for h in hashes if h not in cached]
        try:
            for i in range(0, len(missing), BATCH):
                chunk = missing[i:i + BATCH]
                vecs = self._embed_batch([items[h] for h in chunk])
                self.wh.insert(
                    "embedding_cache", ("content_hash", "model", "vector"),
                    [(h, self.model, list(map(float, v))) for h, v in zip(chunk, vecs)],
                    or_ignore=True,
                )
                cached.update({h: np.asarray(v, dtype=np.float32) for h, v in zip(chunk, vecs)})
                self.embedded += len(chunk)
        except Exception as e:
            # Fuzzy matching still runs; say so once rather than per card.
            self.available = False
            self.error = str(e)
            logger.warning("Embeddings unavailable, using fuzzy matching only: %s", e)
            return {}
        return cached


def _normalise(rows: list[np.ndarray]) -> np.ndarray:
    m = np.vstack(rows)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


def run(wh, run_date: date, use_embeddings: bool = True) -> dict:
    candidates = wh.query(
        """SELECT g.card_uid, g.deck, g.front, g.back
           FROM generated_cards g
           JOIN verified_cards v USING (run_date, card_uid)
           WHERE g.run_date = ? AND v.passed
           ORDER BY g.request_id, g.card_uid""",
        [run_date],
    )
    target_decks = sorted({c["deck"] for c in candidates})

    existing_by_deck: dict[str, list[dict]] = {}
    notes = wh.query("SELECT deck, front, back, content_hash FROM raw_notes WHERE run_date = ?", [run_date])
    prior = wh.query(
        "SELECT deck, front, back FROM card_outcomes WHERE outcome = 'kept' AND run_date < ?",
        [run_date],
    )
    for deck in target_decks:
        pool = [n for n in notes if in_deck(n["deck"], deck)]
        pool += [{**p, "content_hash": content_hash(p["front"], p["back"])}
                 for p in prior if p["deck"] == deck]
        existing_by_deck[deck] = pool

    embedder = Embedder(wh) if use_embeddings else None
    threshold = embedder.threshold if embedder else 0.90
    vectors: dict[str, np.ndarray] = {}
    if embedder and embedder.available:
        texts = {n["content_hash"]: f"{n['front']} {n['back']}"
                 for pool in existing_by_deck.values() for n in pool}
        texts.update({content_hash(c["front"], c["back"]): f"{c['front']} {c['back']}" for c in candidates})
        vectors = embedder.vectors(texts)

    rows = []
    for deck in target_decks:
        pool = list(existing_by_deck[deck])
        for card in (c for c in candidates if c["deck"] == deck):
            is_dup, reason, best = False, "", 0.0

            for n in pool:
                ratio = fuzzy_ratio(card["front"], n["front"])
                if ratio >= FUZZY_THRESHOLD:
                    is_dup, reason, best = True, f"fuzzy {ratio:.2f}: {n['front'][:80]}", ratio
                    break

            card_vec = vectors.get(content_hash(card["front"], card["back"]))
            if not is_dup and card_vec is not None:
                pool_vecs = [(n, vectors[n["content_hash"]]) for n in pool if n["content_hash"] in vectors
                             and vectors[n["content_hash"]].shape == card_vec.shape]
                if pool_vecs:
                    sims = _normalise([v for _, v in pool_vecs]) @ (card_vec / (np.linalg.norm(card_vec) or 1.0))
                    j = int(np.argmax(sims))
                    best = float(sims[j])
                    if best >= threshold:
                        is_dup = True
                        reason = f"semantic {best:.2f}: {pool_vecs[j][0]['front'][:80]}"

            rows.append((run_date, card["card_uid"], is_dup, reason or None, best or None))
            if not is_dup:
                # Later cards in this run must not duplicate this one either.
                pool.append({"front": card["front"], "back": card["back"],
                             "content_hash": content_hash(card["front"], card["back"])})

    wh.replace_partition(
        "dedup_results", run_date, ("run_date", "card_uid", "is_dup", "reason", "similarity"), rows
    )
    dups = sum(1 for r in rows if r[2])
    return {
        "checked": len(rows),
        "duplicates": dups,
        "kept": len(rows) - dups,
        "semantic": bool(embedder and embedder.available),
        "threshold": threshold,
        "embedded_now": embedder.embedded if embedder else 0,
        "embedding_error": embedder.error if embedder else "disabled",
    }
