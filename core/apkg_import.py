"""Import cards from an existing .apkg file into the SQLite database for dedup awareness."""
from __future__ import annotations

import json
import logging
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from core.cards import Card
from core import embeddings
from storage import repository

logger = logging.getLogger(__name__)

# Field separator used by Anki internally
ANKI_FIELD_SEP = chr(0x1F)


def _open_apkg_db(apkg_path: str) -> tuple[sqlite3.Connection, Path]:
    """Extract and open the SQLite database from an .apkg file.
    Handles both legacy (.anki2) and modern zstd-compressed (.anki21b) formats.
    """
    tmpdir = Path(tempfile.mkdtemp())
    with zipfile.ZipFile(apkg_path, "r") as z:
        z.extractall(tmpdir)

    # Try modern format first (zstd compressed)
    anki21b = tmpdir / "collection.anki21b"
    if anki21b.exists():
        try:
            import zstandard
            decompressed = tmpdir / "collection_decompressed.db"
            dctx = zstandard.ZstdDecompressor()
            with open(anki21b, "rb") as fin, open(decompressed, "wb") as fout:
                dctx.copy_stream(fin, fout)
            return sqlite3.connect(str(decompressed)), tmpdir
        except ImportError:
            logger.warning("zstandard not installed, trying legacy format")

    # Fall back to legacy format
    anki2 = tmpdir / "collection.anki2"
    if anki2.exists():
        return sqlite3.connect(str(anki2)), tmpdir

    raise FileNotFoundError("No collection database found in .apkg file")


def _get_art_fields(conn: sqlite3.Connection) -> tuple[int | None, list[str]]:
    """Find the art note type and its field names."""
    c = conn.cursor()

    # Try modern schema (notetypes + fields tables)
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notetypes'")
    if c.fetchone():
        c.execute("SELECT id, name FROM notetypes")
        for ntid, name in c.fetchall():
            c.execute("SELECT name FROM fields WHERE ntid=? ORDER BY ord", (ntid,))
            fields = [r[0] for r in c.fetchall()]
            if "Artwork" in fields and "Artist" in fields:
                return ntid, fields

    # Fall back to legacy schema (col table with JSON models)
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='col'")
    if c.fetchone():
        c.execute("SELECT models FROM col")
        row = c.fetchone()
        if row and row[0]:
            models = json.loads(row[0])
            for mid, m in models.items():
                field_names = [f["name"] for f in m.get("flds", [])]
                if "Artwork" in field_names and "Artist" in field_names:
                    return int(mid), field_names

    return None, []


def _get_deck_id(conn: sqlite3.Connection) -> int | None:
    """Extract the real Anki deck ID from the database."""
    c = conn.cursor()

    # Modern schema: decks table
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='decks'")
    if c.fetchone():
        c.execute("SELECT id FROM decks WHERE id != 1")  # Skip default deck
        row = c.fetchone()
        if row:
            return row[0]

    # Legacy schema: col.decks JSON
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='col'")
    if c.fetchone():
        c.execute("SELECT decks FROM col")
        row = c.fetchone()
        if row and row[0]:
            decks = json.loads(row[0])
            for did, d in decks.items():
                if int(did) != 1:  # Skip default deck
                    return int(did)

    return None


def extract_anki_ids(apkg_path: str, deck_type: str = "artwork") -> dict:
    """Extract and save Anki model/deck IDs from an .apkg without re-importing cards.

    Use this to fix NULL IDs so exports merge into the existing deck.
    """
    conn, tmpdir = _open_apkg_db(apkg_path)
    ntid, field_names = _get_art_fields(conn)
    deck_id = _get_deck_id(conn)
    conn.close()

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    if ntid is None:
        return {"error": "No artwork note type found in .apkg"}

    if ntid and deck_id:
        repository.update_deck_type_anki_ids(deck_type, model_id=ntid, deck_id=deck_id)
        logger.info("Saved Anki IDs: model=%d, deck=%d", ntid, deck_id)

    return {"model_id": ntid, "deck_id": deck_id}


def import_apkg(
    apkg_path: str,
    deck_type: str = "artwork",
    compute_embeddings: bool = True,
    batch_size: int = 20,
) -> dict:
    """
    Import cards from an .apkg file into the database.
    Cards are imported with status 'IMPORTED' so they participate in dedup
    but aren't re-exported.

    Returns stats dict.
    """
    conn, tmpdir = _open_apkg_db(apkg_path)
    c = conn.cursor()

    ntid, field_names = _get_art_fields(conn)
    if ntid is None:
        conn.close()
        return {"error": "No artwork note type found in .apkg"}

    # Extract real Anki IDs so exports merge into this deck
    real_deck_id = _get_deck_id(conn)
    if ntid and real_deck_id:
        repository.update_deck_type_anki_ids(deck_type, model_id=ntid, deck_id=real_deck_id)
        logger.info("Saved Anki IDs: model=%d, deck=%d", ntid, real_deck_id)

    # Get all notes
    c.execute("SELECT flds FROM notes WHERE mid=?", (ntid,))
    rows = c.fetchall()
    conn.close()

    # Get existing cards for dedup check
    existing_cards, _ = repository.get_existing_cards_with_embeddings(deck_type)
    existing_titles = {c.get("Title", "").strip().lower() for c in existing_cards}

    imported = 0
    skipped = 0
    total = len(rows)

    print(f"Found {total} cards in .apkg")

    for i, (flds,) in enumerate(rows):
        values = flds.split(ANKI_FIELD_SEP)
        fields_dict = {}
        for j, fname in enumerate(field_names):
            fields_dict[fname] = values[j] if j < len(values) else ""

        # Skip if title already exists (fast dedup)
        title = fields_dict.get("Title", "").strip().lower()
        if title in existing_titles:
            skipped += 1
            continue

        card = Card(
            deck_type=deck_type,
            fields_json=fields_dict,
            source_topic="imported",
            status="IMPORTED",
        )

        # Compute embedding in batches
        emb = None
        if compute_embeddings:
            card_text = embeddings.card_text_for_embedding(fields_dict)
            emb = embeddings.get_embedding(card_text)

        repository.save_card(card, embedding=emb)
        existing_titles.add(title)
        imported += 1

        if (i + 1) % batch_size == 0:
            print(f"  Progress: {i + 1}/{total} ({imported} imported, {skipped} skipped)")

    # Cleanup
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    stats = {
        "total_in_apkg": total,
        "imported": imported,
        "skipped_duplicates": skipped,
    }
    print(f"\nDone: {imported} imported, {skipped} skipped (already existed)")
    return stats
