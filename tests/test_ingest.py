import sqlite3

from conftest import RUN_DATE

import pytest

from ankigen import ingest as ingest_mod
from ankigen import ingest as ingest  # noqa: F811  (module handle for monkeypatching)
from ankigen.ingest import (
    _front_back, load_notes, read_notes, snapshot, strip_html,
)

ingest_stage = ingest_mod.ingest


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


def test_locked_collection_falls_back_to_copying(make_collection, tmp_path, monkeypatch, caplog):
    """Anki holds the collection open; SQLite's backup blocks instead of failing."""
    import time as _time

    path = make_collection(wal=True)
    monkeypatch.setattr(ingest, "_backup", lambda *a: _time.sleep(30))   # wedged
    snap = ingest.snapshot(path, tmp_path / "snap" / "c.anki2", timeout_s=0.3)
    assert len(read_notes(snap)) == 6                       # still got the data
    assert "copied rather than backed up" in caplog.text


def test_fallback_still_captures_the_wal(make_collection, tmp_path, monkeypatch):
    import time as _time

    path = make_collection(wal=True)
    live = sqlite3.connect(path)
    live.execute("PRAGMA wal_autocheckpoint=0")
    live.execute("INSERT INTO notes VALUES (60, 10, 'Only in the WALyes', '', 0)")
    live.execute("INSERT INTO cards VALUES (600, 60, 100, 0, 0, 0, 2500, 0, 0, 0)")
    live.commit()
    try:
        monkeypatch.setattr(ingest, "_backup", lambda *a: _time.sleep(30))
        snap = ingest.snapshot(path, tmp_path / "snap" / "c.anki2", timeout_s=0.3)
        assert 60 in {n.note_id for n in read_notes(snap)}
    finally:
        live.close()


def test_snapshot_leaves_one_file_behind(make_collection, tmp_path, monkeypatch):
    """The copy path used to leave -wal, -shm and its staging file next to the
    snapshot, so what should be one file was four — and they got committed."""
    import time as _time

    path = make_collection(wal=True)
    monkeypatch.setattr(ingest, "_backup", lambda *a: _time.sleep(30))   # force the copy path
    snap = ingest.snapshot(path, tmp_path / "snap" / "c.anki2", timeout_s=0.3)
    assert [p.name for p in sorted(snap.parent.iterdir())] == ["c.anki2"]


def test_backup_within_reports_failure_rather_than_raising(tmp_path, monkeypatch):
    def boom(*a):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ingest, "_backup", boom)
    assert ingest._backup_within(tmp_path / "a", tmp_path / "b", 1.0) is False


def test_unreadable_collection_raises_a_clear_error(tmp_path, monkeypatch):
    import time as _time

    broken = tmp_path / "broken.anki2"
    broken.write_bytes(b"not a database")
    monkeypatch.setattr(ingest, "_backup", lambda *a: _time.sleep(30))
    with pytest.raises(ingest.CollectionLocked, match="Close Anki desktop"):
        ingest.snapshot(broken, tmp_path / "snap" / "c.anki2", timeout_s=0.3)


def test_strip_html_entities_and_breaks():
    assert strip_html("a&nbsp;&amp;<br>b<div>c</div>") == "a & b c"


def test_front_back_empty():
    assert _front_back(['<img src="x.png">', ""]) == ("", "", False)


def test_ingest_is_idempotent_and_revlog_incremental(wh, modern_collection, tmp_path):
    first = ingest_stage(wh, RUN_DATE, modern_collection, tmp_path / "raw")
    second = ingest_stage(wh, RUN_DATE, modern_collection, tmp_path / "raw")
    assert first["notes"] == second["notes"] == 6
    assert wh.scalar("SELECT COUNT(*) FROM raw_notes") == 6          # replaced, not appended
    assert first["new_reviews"] == 6 and second["new_reviews"] == 0  # incremental by id
    assert len(load_notes(wh, RUN_DATE)) == 6


def test_old_snapshots_are_dropped_and_recent_ones_kept(wh, modern_collection, tmp_path):
    """Only the run's own snapshot is read; keeping every day's forever grew
    the warehouse that rides in the Actions cache by megabytes a day."""
    from datetime import timedelta

    days = [RUN_DATE - timedelta(days=d) for d in (40, 20, 14, 3, 0)]
    pruned = sum(ingest_mod.ingest(wh, day, modern_collection, tmp_path / "raw")
                 ["pruned_snapshots"] for day in days)
    kept = [r["run_date"] for r in wh.query(
        "SELECT DISTINCT run_date FROM raw_notes ORDER BY run_date")]
    assert kept == [RUN_DATE - timedelta(days=14), RUN_DATE - timedelta(days=3), RUN_DATE]
    assert pruned == 2
