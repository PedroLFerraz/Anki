import sqlite3

from conftest import RUN_DATE

from ankigen.ingest import (
    _front_back, ingest, load_notes, read_notes, snapshot, strip_html,
)


def test_modern_schema_deck_names_use_double_colon(modern_collection):
    decks = {n.deck for n in read_notes(modern_collection)}
    assert "DS::SQL::Advanced" in decks
    assert not any("\x1f" in d for d in decks)


def test_front_back_inferred_across_note_types(modern_collection):
    notes = {n.note_id: n for n in read_notes(modern_collection)}
    assert notes[1].front == "What does COALESCE return?"          # HTML stripped
    assert notes[1].back == "The first non-NULL argument."
    # Frente / Imagem / Audio / Verso: media-only fields are skipped.
    assert (notes[5].front, notes[5].back) == ("der Hund", "the dog")


def test_cloze_detected_and_stripped(modern_collection):
    note = next(n for n in read_notes(modern_collection) if n.note_id == 6)
    assert note.is_cloze
    assert note.front == "The mitochondria makes ATP."


def test_review_stats_carried(modern_collection):
    note = next(n for n in read_notes(modern_collection) if n.note_id == 2)
    assert (note.lapses, note.ease, note.interval_days) == (3, 1900, 3)


def test_filtered_deck_uses_original_deck(make_collection):
    path = make_collection()
    con = sqlite3.connect(path)
    con.execute("INSERT INTO decks VALUES (999, 'Filtered Review')")
    con.execute("UPDATE cards SET odid = did, did = 999 WHERE nid = 1")
    con.commit(); con.close()
    note = next(n for n in read_notes(path) if n.note_id == 1)
    assert note.deck == "DS::SQL"


def test_orphan_notes_and_empty_fronts_skipped(make_collection):
    path = make_collection()
    con = sqlite3.connect(path)
    con.execute("INSERT INTO notes VALUES (77, 10, 'orphan\x1fno cards', '', 0)")
    con.commit(); con.close()
    assert 77 not in {n.note_id for n in read_notes(path)}


def test_legacy_schema(legacy_collection):
    [note] = read_notes(legacy_collection)
    assert note.deck == "DS::SQL"
    assert note.notetype == "Basic"
    assert (note.front, note.back, note.lapses) == ("What is an index?", "A lookup structure.", 1)


def test_snapshot_includes_uncheckpointed_wal(make_collection, tmp_path):
    """The live collection keeps recent writes in -wal; a plain file copy loses them."""
    path = make_collection(wal=True)
    live = sqlite3.connect(path)
    live.execute("PRAGMA wal_autocheckpoint=0")
    live.execute("INSERT INTO notes VALUES (50, 10, 'Fresh card\x1fjust added', '', 0)")
    live.execute("INSERT INTO cards VALUES (500, 50, 100, 0, 0, 0, 2500, 0, 0, 0)")
    live.commit()                     # connection stays open: no checkpoint into the main file
    try:
        snap = snapshot(path, tmp_path / "snap" / "c.anki2")
        assert 50 in {n.note_id for n in read_notes(snap)}
    finally:
        live.close()


def test_strip_html_entities_and_breaks():
    assert strip_html("a&nbsp;&amp;<br>b<div>c</div>") == "a & b c"


def test_front_back_empty():
    assert _front_back(['<img src="x.png">', ""]) == ("", "", False)


def test_ingest_is_idempotent_and_revlog_incremental(wh, modern_collection, tmp_path):
    first = ingest(wh, RUN_DATE, modern_collection, tmp_path / "raw")
    second = ingest(wh, RUN_DATE, modern_collection, tmp_path / "raw")
    assert first["notes"] == second["notes"] == 6
    assert wh.scalar("SELECT COUNT(*) FROM raw_notes") == 6          # replaced, not appended
    assert first["new_reviews"] == 6 and second["new_reviews"] == 0  # incremental by id
    assert len(load_notes(wh, RUN_DATE)) == 6
