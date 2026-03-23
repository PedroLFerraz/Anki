import json
import sqlite3

import numpy as np

from core.cards import Card, DeckType, GenerationRun
from storage.database import get_connection


# --- Deck Types ---

def get_deck_type(name: str) -> DeckType | None:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT name, fields_schema, front_template, back_template, css FROM deck_types WHERE name = ?", (name,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return DeckType(
        name=row[0],
        fields_schema=json.loads(row[1]),
        front_template=row[2],
        back_template=row[3],
        css=row[4],
    )


def get_all_deck_types() -> list[DeckType]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT name, fields_schema, front_template, back_template, css FROM deck_types")
    rows = c.fetchall()
    conn.close()
    return [
        DeckType(name=r[0], fields_schema=json.loads(r[1]), front_template=r[2], back_template=r[3], css=r[4])
        for r in rows
    ]


# --- Cards ---

def _serialize_embedding(emb: np.ndarray | None) -> bytes | None:
    if emb is None:
        return None
    return emb.tobytes()


def _deserialize_embedding(data: bytes | None) -> np.ndarray | None:
    if data is None:
        return None
    return np.frombuffer(data, dtype=np.float32)


def save_card(card: Card, embedding: np.ndarray | None = None) -> int:
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO cards (deck_type, fields_json, image_filename, audio_filename, embedding, source_topic, run_id, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            card.deck_type,
            json.dumps(card.fields_json),
            card.image_filename,
            card.audio_filename,
            _serialize_embedding(embedding),
            card.source_topic,
            card.run_id,
            card.status,
        ),
    )
    card_id = c.lastrowid
    conn.commit()
    conn.close()
    return card_id


def update_card_status(card_id: int, status: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE cards SET status = ? WHERE id = ?", (status, card_id))
    conn.commit()
    conn.close()


def update_card_media(card_id: int, image_filename: str | None = None, audio_filename: str | None = None):
    conn = get_connection()
    c = conn.cursor()
    if image_filename is not None:
        c.execute("UPDATE cards SET image_filename = ? WHERE id = ?", (image_filename, card_id))
    if audio_filename is not None:
        c.execute("UPDATE cards SET audio_filename = ? WHERE id = ?", (audio_filename, card_id))
    conn.commit()
    conn.close()


def get_cards(deck_type: str | None = None, status: str | None = None) -> list[Card]:
    conn = get_connection()
    c = conn.cursor()

    query = "SELECT id, deck_type, fields_json, image_filename, audio_filename, created_at, source_topic, run_id, status FROM cards WHERE 1=1"
    params = []
    if deck_type:
        query += " AND deck_type = ?"
        params.append(deck_type)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id DESC"

    c.execute(query, params)
    rows = c.fetchall()
    conn.close()

    return [
        Card(
            id=r[0], deck_type=r[1], fields_json=json.loads(r[2]),
            image_filename=r[3], audio_filename=r[4], created_at=r[5],
            source_topic=r[6], run_id=r[7], status=r[8],
        )
        for r in rows
    ]


def get_existing_cards_with_embeddings(deck_type: str) -> tuple[list[dict], list[np.ndarray | None]]:
    """Returns (list_of_fields_dicts, list_of_embeddings) for duplicate detection."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT fields_json, embedding FROM cards WHERE deck_type = ? AND status != 'REJECTED'",
        (deck_type,),
    )
    rows = c.fetchall()
    conn.close()

    cards = []
    embeddings = []
    for fields_str, emb_bytes in rows:
        cards.append(json.loads(fields_str))
        embeddings.append(_deserialize_embedding(emb_bytes))
    return cards, embeddings


# --- Runs ---

def create_run(run: GenerationRun) -> int:
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO runs (topic, deck_name, deck_type, persona, total_generated, total_accepted)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (run.topic, run.deck_name, run.deck_type, run.persona, run.total_generated, run.total_accepted),
    )
    run_id = c.lastrowid
    conn.commit()
    conn.close()
    return run_id


def update_run_accepted(run_id: int, total_accepted: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE runs SET total_accepted = ? WHERE run_id = ?", (total_accepted, run_id))
    conn.commit()
    conn.close()


# --- Analytics ---

def get_analytics(deck_type: str | None = None) -> list[dict]:
    conn = get_connection()
    c = conn.cursor()

    query = """
        SELECT
            c.source_topic as topic,
            c.deck_type,
            COUNT(*) as total_cards,
            SUM(CASE WHEN c.status IN ('ACCEPTED', 'EXPORTED') THEN 1 ELSE 0 END) as accepted,
            SUM(CASE WHEN c.status = 'REJECTED' THEN 1 ELSE 0 END) as rejected
        FROM cards c
    """
    params = []
    if deck_type:
        query += " WHERE c.deck_type = ?"
        params.append(deck_type)
    query += " GROUP BY c.source_topic, c.deck_type"

    c.execute(query, params)
    cols = [desc[0] for desc in c.description]
    rows = [dict(zip(cols, row)) for row in c.fetchall()]
    conn.close()
    return rows
