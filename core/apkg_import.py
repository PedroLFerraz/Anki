"""Import .apkg files to extract cards as context for generation."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

FIELD_SEPARATOR = "\x1f"


def import_apkg(apkg_path: str | Path) -> tuple[str, list[dict]]:
    """Extract cards from an .apkg file.

    Returns (deck_name, cards) where cards is a list of
    {"question": str, "answer": str} dicts.
    """
    apkg_path = Path(apkg_path)
    if not apkg_path.exists():
        raise FileNotFoundError(f"File not found: {apkg_path}")
    if not apkg_path.suffix == ".apkg":
        raise ValueError(f"Not an .apkg file: {apkg_path}")

    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(apkg_path, "r") as z:
            z.extractall(tmpdir)

        db_path = Path(tmpdir) / "collection.anki2"
        if not db_path.exists():
            db_path = Path(tmpdir) / "collection.anki21"
        if not db_path.exists():
            db_path = Path(tmpdir) / "collection.anki21b"
        if not db_path.exists():
            raise ValueError("No collection database found in .apkg file")

        conn = sqlite3.connect(str(db_path))
        deck_name = _extract_deck_name(conn)
        cards = _extract_cards(conn)
        conn.close()

    logger.info("Imported %d cards from '%s' (deck: %s)", len(cards), apkg_path.name, deck_name)
    return deck_name, cards


def _extract_deck_name(conn: sqlite3.Connection) -> str:
    """Get the primary deck name from the collection."""
    try:
        row = conn.execute("SELECT decks FROM col").fetchone()
        if row:
            decks = json.loads(row[0])
            for deck_id, deck in decks.items():
                if deck_id == "1":
                    continue  # skip Anki's built-in default deck (ID 1)
                name = deck.get("name", "")
                if name:
                    return name
    except Exception as e:
        logger.warning("Could not extract deck name: %s", e)
    return "Imported Deck"


def _extract_cards(conn: sqlite3.Connection) -> list[dict]:
    """Extract question/answer pairs from notes."""
    cards = []

    try:
        rows = conn.execute("SELECT flds, mid FROM notes").fetchall()
    except sqlite3.OperationalError as e:
        logger.error("Failed to read notes table: %s", e)
        return []

    for flds_raw, mid in rows:
        fields = flds_raw.split(FIELD_SEPARATOR)
        if len(fields) < 2:
            # Single-field note (e.g. cloze) — use full text
            text = _strip_html(fields[0]) if fields else ""
            if len(text) > 5:
                # Strip cloze markers for context
                text = re.sub(r'\{\{c\d+::(.*?)(?:::[^}]*)?\}\}', r'\1', text)
                cards.append({"question": text, "answer": text})
            continue

        q = _strip_html(fields[0])
        a = _strip_html(fields[1])
        # For multi-field notes, try remaining fields too
        if len(fields) > 2:
            extra_text = " ".join(_strip_html(f) for f in fields[2:] if _strip_html(f))
            if extra_text and len(a) < 3:
                a = extra_text

        # If question is empty (e.g. image-only card), use answer as context
        if len(q) < 3 and len(a) >= 3:
            q = a
        elif len(q) < 3 and len(a) < 3:
            continue

        cards.append({"question": q, "answer": a})

    return cards


def _strip_html(text: str) -> str:
    """Remove HTML tags, media references, and clean up whitespace."""
    # Remove img tags and sound references
    text = re.sub(r'<img[^>]*>', '', text)
    text = re.sub(r'\[sound:[^\]]*\]', '', text)
    # Remove all HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text
