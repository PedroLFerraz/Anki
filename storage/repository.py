from __future__ import annotations

import json

import numpy as np
from storage.database import get_connection


def _serialize_embedding(emb: np.ndarray | None) -> bytes | None:
    if emb is None:
        return None
    return emb.tobytes()


def _deserialize_embedding(data: bytes | None) -> np.ndarray | None:
    if data is None:
        return None
    return np.frombuffer(data, dtype=np.float32)


def save_card(
    question: str, answer: str, topic: str,
    embedding: np.ndarray | None = None, status: str = "GENERATED",
    card_type: str = "basic", extra_fields: dict | None = None,
) -> int:
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO cards (question, answer, topic, embedding, status, card_type, extra_fields) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (question, answer, topic, _serialize_embedding(embedding), status,
         card_type, json.dumps(extra_fields) if extra_fields else None),
    )
    card_id = c.lastrowid
    conn.commit()
    conn.close()
    return card_id


def update_card_extra_fields(card_id: int, extra_fields: dict):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE cards SET extra_fields = ? WHERE id = ?", (json.dumps(extra_fields), card_id))
    conn.commit()
    conn.close()


def update_card_status(card_id: int, status: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE cards SET status = ? WHERE id = ?", (status, card_id))
    conn.commit()
    conn.close()


def get_cards(topic: str | None = None, status: str | None = None) -> list[dict]:
    conn = get_connection()
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
        # Parse extra_fields JSON
        if d.get("extra_fields"):
            d["extra_fields"] = json.loads(d["extra_fields"])
        else:
            d["extra_fields"] = {}
        rows.append(d)
    conn.close()
    return rows


def get_context_cards_with_embeddings() -> tuple[list[dict], list[np.ndarray | None]]:
    """Returns (cards, embeddings) from CONTEXT cards only (imported decks)."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT question, answer, topic, embedding FROM cards WHERE status = 'CONTEXT'")
    rows = c.fetchall()
    conn.close()

    cards = []
    embeddings = []
    for q, a, t, emb_bytes in rows:
        cards.append({"Question": q, "Answer": a, "topic": t})
        embeddings.append(_deserialize_embedding(emb_bytes))
    return cards, embeddings


def save_context_cards(cards: list[dict], source: str = "import") -> int:
    """Bulk-insert imported cards as CONTEXT. Returns count saved."""
    conn = get_connection()
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
    conn.close()
    return count


def delete_context_cards() -> int:
    """Delete all CONTEXT cards."""
    return delete_cards_by_status("CONTEXT")


def get_context_count() -> int:
    """Return the number of CONTEXT cards."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM cards WHERE status = 'CONTEXT'")
    count = c.fetchone()[0]
    conn.close()
    return count


def delete_cards_by_status(status: str, topic: str | None = None) -> int:
    conn = get_connection()
    c = conn.cursor()
    if topic:
        c.execute("DELETE FROM cards WHERE status = ? AND topic = ?", (status, topic))
    else:
        c.execute("DELETE FROM cards WHERE status = ?", (status,))
    count = c.rowcount
    conn.commit()
    conn.close()
    return count
