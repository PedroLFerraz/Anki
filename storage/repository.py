from __future__ import annotations

import json
import logging

import numpy as np
from storage.database import get_connection

logger = logging.getLogger(__name__)

VALID_STATUSES = {"GENERATED", "ACCEPTED", "REJECTED", "DUPLICATE", "EXPORTED", "CONTEXT"}


def _serialize_embedding(emb: np.ndarray | None) -> bytes | None:
    if emb is None:
        return None
    return emb.tobytes()


def _deserialize_embedding(data: bytes | None) -> np.ndarray | None:
    if data is None:
        return None
    try:
        return np.frombuffer(data, dtype=np.float32)
    except (ValueError, TypeError) as e:
        logger.warning("Could not deserialize embedding: %s", e)
        return None


def _parse_extra_fields(raw: str | None) -> dict:
    """Safely parse extra_fields JSON, returning {} on failure."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("Corrupted extra_fields JSON: %s", e)
        return {}


def _validate_status(status: str):
    """Raise ValueError if status is not a known value."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}")


def save_card(
    question: str, answer: str, topic: str,
    embedding: np.ndarray | None = None, status: str = "GENERATED",
    card_type: str = "basic", extra_fields: dict | None = None,
) -> int:
    _validate_status(status)
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO cards (question, answer, topic, embedding, status, card_type, extra_fields) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (question, answer, topic, _serialize_embedding(embedding), status,
             card_type, json.dumps(extra_fields) if extra_fields else None),
        )
        card_id = c.lastrowid
        conn.commit()
        return card_id
    finally:
        conn.close()


def update_card_content(card_id: int, question: str, answer: str, extra_fields: dict | None = None):
    """Update the question, answer, and optionally extra_fields of a card."""
    conn = get_connection()
    try:
        c = conn.cursor()
        if extra_fields is not None:
            c.execute("UPDATE cards SET question = ?, answer = ?, extra_fields = ? WHERE id = ?",
                      (question, answer, json.dumps(extra_fields), card_id))
        else:
            c.execute("UPDATE cards SET question = ?, answer = ? WHERE id = ?",
                      (question, answer, card_id))
        conn.commit()
    finally:
        conn.close()


def update_card_extra_fields(card_id: int, extra_fields: dict):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE cards SET extra_fields = ? WHERE id = ?", (json.dumps(extra_fields), card_id))
        conn.commit()
    finally:
        conn.close()


def update_card_status(card_id: int, status: str):
    _validate_status(status)
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE cards SET status = ? WHERE id = ?", (status, card_id))
        conn.commit()
    finally:
        conn.close()


def update_cards_status_batch(card_ids: list[int], status: str) -> int:
    """Update status for multiple cards at once. Returns count updated."""
    if not card_ids:
        return 0
    _validate_status(status)
    conn = get_connection()
    try:
        c = conn.cursor()
        placeholders = ",".join("?" for _ in card_ids)
        c.execute(f"UPDATE cards SET status = ? WHERE id IN ({placeholders})",
                  [status] + list(card_ids))
        count = c.rowcount
        conn.commit()
        return count
    finally:
        conn.close()


def get_cards(topic: str | None = None, status: str | None = None) -> list[dict]:
    conn = get_connection()
    try:
        c = conn.cursor()

        query = "SELECT id, question, answer, topic, status, created_at, card_type, extra_fields FROM cards WHERE 1=1"
        params = []
        if topic:
            query += " AND topic = ?"
            params.append(topic)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY id DESC"

        c.execute(query, params)
        cols = [desc[0] for desc in c.description]
        rows = []
        for row in c.fetchall():
            d = dict(zip(cols, row))
            d["extra_fields"] = _parse_extra_fields(d.get("extra_fields"))
            rows.append(d)
        return rows
    finally:
        conn.close()


def get_card_by_id(card_id: int) -> dict | None:
    """Get a single card by ID. Returns None if not found."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT id, question, answer, topic, status, created_at, card_type, extra_fields FROM cards WHERE id = ?",
                  (card_id,))
        row = c.fetchone()
        if not row:
            return None
        cols = [desc[0] for desc in c.description]
        d = dict(zip(cols, row))
        d["extra_fields"] = _parse_extra_fields(d.get("extra_fields"))
        return d
    finally:
        conn.close()


def delete_card_by_id(card_id: int) -> bool:
    """Delete a single card by ID. Returns True if found and deleted."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        deleted = c.rowcount > 0
        conn.commit()
        return deleted
    finally:
        conn.close()


def get_card_counts(topic: str | None = None) -> dict:
    """Get card counts grouped by status and card_type.
    Returns: {"total": int, "by_status": {status: count}, "by_type": {type: count}}
    """
    conn = get_connection()
    try:
        c = conn.cursor()
        params = []
        where = ""
        if topic:
            where = " WHERE topic = ?"
            params.append(topic)

        # Total
        c.execute(f"SELECT COUNT(*) FROM cards{where}", params)
        total = c.fetchone()[0]

        # By status
        c.execute(f"SELECT status, COUNT(*) FROM cards{where} GROUP BY status", params)
        by_status = dict(c.fetchall())

        # By type
        c.execute(f"SELECT card_type, COUNT(*) FROM cards{where} GROUP BY card_type", params)
        by_type = dict(c.fetchall())

        return {"total": total, "by_status": by_status, "by_type": by_type}
    finally:
        conn.close()


def get_topics() -> list[str]:
    """Get all unique non-null topics from the cards table."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT DISTINCT topic FROM cards WHERE topic IS NOT NULL AND topic != '' ORDER BY topic")
        return [row[0] for row in c.fetchall()]
    finally:
        conn.close()


def get_context_cards_with_embeddings() -> tuple[list[dict], list[np.ndarray | None]]:
    """Returns (cards, embeddings) from CONTEXT cards only (imported decks)."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT question, answer, topic, embedding FROM cards WHERE status = 'CONTEXT'")
        rows = c.fetchall()

        cards = []
        embeddings = []
        for q, a, t, emb_bytes in rows:
            cards.append({"Question": q, "Answer": a, "topic": t})
            embeddings.append(_deserialize_embedding(emb_bytes))
        return cards, embeddings
    finally:
        conn.close()


def save_context_cards(cards: list[dict], source: str = "import") -> int:
    """Bulk-insert imported cards as CONTEXT. Returns count saved."""
    conn = get_connection()
    try:
        c = conn.cursor()
        count = 0
        for card in cards:
            q = card.get("question", "").strip()
            a = card.get("answer", "").strip()
            if not q:
                continue
            c.execute(
                "INSERT INTO cards (question, answer, topic, status, card_type) VALUES (?, ?, ?, 'CONTEXT', 'context')",
                (q, a, source),
            )
            count += 1
        conn.commit()
        return count
    finally:
        conn.close()


def delete_context_cards() -> int:
    """Delete all CONTEXT cards."""
    return delete_cards_by_status("CONTEXT")


def get_context_count() -> int:
    """Return the number of CONTEXT cards."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM cards WHERE status = 'CONTEXT'")
        return c.fetchone()[0]
    finally:
        conn.close()


def delete_cards_by_status(status: str, topic: str | None = None) -> int:
    conn = get_connection()
    try:
        c = conn.cursor()
        if topic:
            c.execute("DELETE FROM cards WHERE status = ? AND topic = ?", (status, topic))
        else:
            c.execute("DELETE FROM cards WHERE status = ?", (status,))
        count = c.rowcount
        conn.commit()
        return count
    finally:
        conn.close()
