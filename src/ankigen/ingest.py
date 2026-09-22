"""Read an Anki collection into the warehouse.

The live collection is never opened for reading directly: it is snapshotted
first with SQLite's backup API, which (unlike a file copy) also captures pages
still sitting in the `-wal` file — i.e. your most recent reviews.
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

FIELD_SEP = "\x1f"
# Modern Anki stores deck hierarchy with \x1f; the UI (and this project) uses "::".
DECK_SEP = "\x1f"
CLOZE_RE = re.compile(r"\{\{c\d+::(.*?)(?:::[^}]*)?\}\}", re.DOTALL)


class CollectionLocked(RuntimeError):
    pass


@dataclass(frozen=True)
class Note:
    note_id: int
    deck: str
    notetype: str
    front: str
    back: str
    tags: str
    is_cloze: bool
    lapses: int
    ease: int
    reps: int
    interval_days: int
    queue: int
    modified_at: int

    @property
    def content_hash(self) -> str:
        return content_hash(self.front, self.back)


def content_hash(front: str, back: str) -> str:
    return hashlib.sha1(f"{front}{FIELD_SEP}{back}".encode("utf-8")).hexdigest()


def strip_html(text: str) -> str:
    """Plain text from an Anki field: no tags, media refs or entities."""
    text = re.sub(r"<img[^>]*>", " ", text)
    text = re.sub(r"\[sound:[^\]]*\]", " ", text)
    text = re.sub(r"<br\s*/?>|</(div|p|li)>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def strip_cloze(text: str) -> str:
    return CLOZE_RE.sub(r"\1", text)


# ---------------------------------------------------------------- snapshot

def snapshot(collection: str | Path, dest: str | Path, retries: int = 3) -> Path:
    """Consistent point-in-time copy of the collection, WAL included."""
    collection, dest = Path(collection), Path(dest)
    if not collection.exists():
        raise FileNotFoundError(
            f"Anki collection not found: {collection}. Set ANKI_COLLECTION_PATH."
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            src = sqlite3.connect(f"{collection.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
            try:
                dst = sqlite3.connect(dest)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
            return dest
        except sqlite3.OperationalError as e:
            last_error = e
            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                raise
            time.sleep(2 * (attempt + 1))

    raise CollectionLocked(
        "The Anki collection is locked — Anki desktop holds it exclusively while "
        f"open. Close Anki and retry. ({last_error})"
    )


# ---------------------------------------------------------------- parsing

def _is_modern(con: sqlite3.Connection) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='notetypes'"
    ).fetchone() is not None


def _decks(con: sqlite3.Connection, modern: bool) -> dict[int, str]:
    if modern:
        return {did: name.replace(DECK_SEP, "::") for did, name in con.execute("SELECT id, name FROM decks")}
    raw = json.loads(con.execute("SELECT decks FROM col").fetchone()[0])
    return {int(did): d["name"] for did, d in raw.items()}


def _notetypes(con: sqlite3.Connection, modern: bool) -> dict[int, tuple[str, list[str]]]:
    if modern:
        names = dict(con.execute("SELECT id, name FROM notetypes"))
        fields: dict[int, list[str]] = {}
        for ntid, _ord, fname in con.execute("SELECT ntid, ord, name FROM fields ORDER BY ntid, ord"):
            fields.setdefault(ntid, []).append(fname)
        return {mid: (name, fields.get(mid, [])) for mid, name in names.items()}
    raw = json.loads(con.execute("SELECT models FROM col").fetchone()[0])
    return {int(mid): (m["name"], [f["name"] for f in m.get("flds", [])]) for mid, m in raw.items()}


def _front_back(raw_fields: list[str]) -> tuple[str, str, bool]:
    """Infer front and back without knowing the note type's semantics.

    Real collections mix dozens of note types (Front/Back, Frente/Verso,
    Vorderseite/Rückseite, image-first art cards...). The first two fields that
    still carry text after stripping media are the best general guess.
    """
    for raw in raw_fields:
        if CLOZE_RE.search(raw):
            text = strip_html(strip_cloze(raw))
            return text, text, True

    texts = [t for t in (strip_html(f) for f in raw_fields) if t]
    if not texts:
        return "", "", False
    return texts[0], texts[1] if len(texts) > 1 else "", False


def read_notes(collection: str | Path) -> list[Note]:
    con = sqlite3.connect(f"{Path(collection).resolve().as_uri()}?mode=ro", uri=True)
    try:
        modern = _is_modern(con)
        decks = _decks(con, modern)
        notetypes = _notetypes(con, modern)

        # One row per note. A note's cards can live in different decks; its home is
        # the deck of its first card. Cards temporarily in a filtered deck carry
        # their real deck in `odid`.
        stats = {}
        for row in con.execute(
            """SELECT nid,
                      CASE WHEN odid != 0 THEN odid ELSE did END AS home_deck,
                      ord, lapses, factor, reps, ivl, queue
               FROM cards ORDER BY nid, ord"""
        ):
            nid, did, _ord, lapses, factor, reps, ivl, queue = row
            s = stats.get(nid)
            if s is None:
                stats[nid] = {"did": did, "lapses": lapses, "ease": factor or 0,
                              "reps": reps, "ivl": ivl, "queue": queue}
            else:
                s["lapses"] = max(s["lapses"], lapses)
                if factor and (not s["ease"] or factor < s["ease"]):
                    s["ease"] = factor
                s["reps"] += reps
                s["ivl"] = max(s["ivl"], ivl)

        notes = []
        for nid, mid, flds, tags, mod in con.execute("SELECT id, mid, flds, tags, mod FROM notes"):
            s = stats.get(nid)
            if s is None:  # orphaned note with no cards
                continue
            front, back, is_cloze = _front_back(flds.split(FIELD_SEP))
            if not front:
                continue
            notes.append(Note(
                note_id=nid,
                deck=decks.get(s["did"], "Unknown"),
                notetype=notetypes.get(mid, ("Unknown", []))[0],
                front=front,
                back=back,
                tags=(tags or "").strip(),
                is_cloze=is_cloze,
                lapses=s["lapses"],
                ease=s["ease"],
                reps=s["reps"],
                interval_days=s["ivl"],
                queue=s["queue"],
                modified_at=mod,
            ))
        return notes
    finally:
        con.close()


def read_revlog(collection: str | Path, after_id: int = 0) -> list[tuple]:
    con = sqlite3.connect(f"{Path(collection).resolve().as_uri()}?mode=ro", uri=True)
    try:
        return con.execute(
            "SELECT id, cid, ease, ivl, time, type FROM revlog WHERE id > ? ORDER BY id",
            [after_id],
        ).fetchall()
    finally:
        con.close()


# ---------------------------------------------------------------- stage

NOTE_COLUMNS = (
    "run_date", "note_id", "deck", "notetype", "front", "back", "tags", "is_cloze",
    "content_hash", "lapses", "ease", "reps", "interval_days", "queue", "modified_at",
)


def ingest(wh, run_date: date, collection: str | Path, raw_dir: str | Path) -> dict:
    """Snapshot the collection and load it: notes as a full daily snapshot,
    reviews incrementally (only ids newer than what's already loaded)."""
    snap = snapshot(collection, Path(raw_dir) / str(run_date) / "collection.anki2")
    notes = read_notes(snap)

    wh.replace_partition("raw_notes", run_date, NOTE_COLUMNS, [
        (run_date, n.note_id, n.deck, n.notetype, n.front, n.back, n.tags, n.is_cloze,
         n.content_hash, n.lapses, n.ease, n.reps, n.interval_days, n.queue, n.modified_at)
        for n in notes
    ])

    last_review = wh.scalar("SELECT COALESCE(MAX(review_id), 0) FROM raw_revlog")
    reviews = read_revlog(snap, after_id=last_review)
    wh.insert(
        "raw_revlog",
        ("review_id", "card_id", "ease", "interval", "time_ms", "review_type", "loaded_on"),
        [(*r, run_date) for r in reviews],
        or_ignore=True,
    )

    decks = len({n.deck for n in notes})
    logger.info("Ingested %d notes across %d decks, %d new reviews", len(notes), decks, len(reviews))
    return {"notes": len(notes), "decks": decks, "new_reviews": len(reviews), "snapshot": str(snap)}


def load_notes(wh, run_date: date) -> list[Note]:
    rows = wh.query(
        """SELECT note_id, deck, notetype, front, back, tags, is_cloze, lapses, ease,
                  reps, interval_days, queue, modified_at
           FROM raw_notes WHERE run_date = ?""",
        [run_date],
    )
    return [Note(**r) for r in rows]
