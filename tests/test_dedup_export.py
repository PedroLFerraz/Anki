import json
import sqlite3
import zipfile

import numpy as np
import pytest
from conftest import RUN_DATE

from ankigen import dedup, export, generate
from ankigen.ingest import ingest


def _seed(wh, cards, passed=True, request_reason="topic"):
    """Put generated cards (all passing verification) into the warehouse."""
    wh.replace_partition("requests", RUN_DATE,
                         ("run_date", "request_id", "deck", "topic", "card_type", "n", "reason", "focus", "prompt"),
                         [(RUN_DATE, "r1", cards[0][1], "t", "basic", len(cards), request_reason, None, "p")])
    wh.replace_partition("generated_cards", RUN_DATE, generate.GENERATED_COLUMNS, [
        (RUN_DATE, uid, "r1", deck, "basic", front, back,
         json.dumps({"Question": front, "Answer": back}), "", "m", 0, 0)
        for uid, deck, front, back in cards
    ])
    wh.replace_partition("verified_cards", RUN_DATE, ("run_date", "card_uid", "passed", "score", "reason"),
                         [(RUN_DATE, c[0], passed, 0.9, "") for c in cards])


# ---------------------------------------------------------------- dedup

def test_fuzzy_ratio_ignores_case_and_articles():
    assert dedup.fuzzy_ratio("The Mitochondria", "mitochondria") == 1.0
    assert dedup.fuzzy_ratio("What is Python?", "How does SQL work?") < 0.85


def test_cosine_zero_vector():
    assert dedup.cosine_similarity(np.array([1.0, 2.0]), np.zeros(2)) == 0.0


def test_duplicates_of_existing_notes_are_dropped(wh, modern_collection, tmp_path, fake_embeddings, cfg):
    ingest(wh, RUN_DATE, modern_collection, tmp_path / "raw")
    _seed(wh, [
        ("u1", "DS::SQL", "What is a CTE?", "A named subquery."),                 # fuzzy dup of note 2
        # Reworded: fuzzy ratio 0.54 misses it, embedding cosine 0.95 catches it.
        ("u2", "DS::SQL", "LATERAL join: what is it?", "A join whose right side can reference the left."),
        ("u3", "DS::SQL", "What is a covering index?", "An index containing every queried column."),
    ])
    result = dedup.run(wh, RUN_DATE)
    outcome = {r["card_uid"]: r["is_dup"] for r in wh.query("SELECT * FROM dedup_results")}
    assert outcome == {"u1": True, "u2": True, "u3": False}
    reasons = {r["card_uid"]: r["reason"] for r in wh.query("SELECT * FROM dedup_results")}
    assert reasons["u1"].startswith("fuzzy")
    assert reasons["u2"].startswith("semantic")      # and against a *subdeck* note
    assert result["semantic"] is True


def test_low_threshold_model_catches_more(wh, modern_collection, tmp_path, fake_embeddings, cfg, monkeypatch):
    """A model whose scores run lower needs a lower threshold to catch the same pair."""
    from ankigen import dedup as d
    ingest(wh, RUN_DATE, modern_collection, tmp_path / "raw")
    _seed(wh, [("u1", "DS::SQL", "LATERAL join: what is it?",
                "A join whose right side can reference the left.")])
    monkeypatch.setattr(cfg, "semantic_threshold", 0.99)
    strict = d.run(wh, RUN_DATE)
    assert strict["threshold"] == 0.99 and strict["duplicates"] == 0   # too strict to fire
    monkeypatch.setattr(cfg, "semantic_threshold", 0.60)
    relaxed = d.run(wh, RUN_DATE)
    assert relaxed["threshold"] == 0.60 and relaxed["duplicates"] == 1


def test_duplicates_within_the_same_run(wh, modern_collection, tmp_path, fake_embeddings, cfg):
    ingest(wh, RUN_DATE, modern_collection, tmp_path / "raw")
    _seed(wh, [
        ("u1", "DS::SQL", "What does EXPLAIN ANALYZE show?", "Actual timings."),
        ("u2", "DS::SQL", "What does EXPLAIN ANALYZE show?", "Real run times."),
    ])
    dedup.run(wh, RUN_DATE)
    assert wh.scalar("SELECT COUNT(*) FROM dedup_results WHERE is_dup") == 1


def test_embedding_cache_means_second_run_embeds_nothing(wh, modern_collection, tmp_path, fake_embeddings, cfg):
    ingest(wh, RUN_DATE, modern_collection, tmp_path / "raw")
    _seed(wh, [("u1", "DS::SQL", "What is a covering index?", "Every queried column.")])
    first = dedup.run(wh, RUN_DATE)
    second = dedup.run(wh, RUN_DATE)
    assert first["embedded_now"] > 0 and second["embedded_now"] == 0


def test_embedding_outage_falls_back_to_fuzzy(wh, modern_collection, tmp_path, monkeypatch, cfg):
    ingest(wh, RUN_DATE, modern_collection, tmp_path / "raw")
    _seed(wh, [("u1", "DS::SQL", "What is a CTE?", "x"), ("u2", "DS::SQL", "Unrelated new idea", "y")])

    def down(self, texts):
        raise ConnectionError("ollama not running")

    monkeypatch.setattr(dedup.Embedder, "_embed_batch", down)
    result = dedup.run(wh, RUN_DATE)
    assert result["semantic"] is False and "ollama not running" in result["embedding_error"]
    assert result["duplicates"] == 1                           # fuzzy still caught the CTE card


def test_verify_failures_are_not_deduped(wh, modern_collection, tmp_path, fake_embeddings, cfg):
    ingest(wh, RUN_DATE, modern_collection, tmp_path / "raw")
    _seed(wh, [("u1", "DS::SQL", "Anything", "x")], passed=False)
    assert dedup.run(wh, RUN_DATE)["checked"] == 0


# ---------------------------------------------------------------- export

def _kept(wh, cards, **kw):
    _seed(wh, cards, **kw)
    wh.replace_partition("dedup_results", RUN_DATE, ("run_date", "card_uid", "is_dup", "reason", "similarity"),
                         [(RUN_DATE, c[0], False, None, None) for c in cards])


def _notes_in(apkg):
    with zipfile.ZipFile(apkg) as z:
        z.extract("collection.anki2", apkg.parent / "x")
    con = sqlite3.connect(apkg.parent / "x" / "collection.anki2")
    try:
        decks = json.loads(con.execute("SELECT decks FROM col").fetchone()[0])
        notes = con.execute("SELECT guid, flds, tags FROM notes").fetchall()
    finally:
        con.close()
    return {d["name"] for d in decks.values()}, notes


def test_export_writes_inbox_package_with_tags(wh, tmp_path):
    _kept(wh, [("u1", "DS::SQL", "What is a CTE?", "A named subquery.")], request_reason="weak_card")
    result = export.run(wh, RUN_DATE, tmp_path / "out")
    decks, notes = _notes_in(tmp_path / "out" / str(RUN_DATE) / f"ankigen_{RUN_DATE}.apkg")
    assert result["kept"] == 1
    assert "DS::SQL" in decks          # straight into the real deck, no merge step
    [(guid, flds, tags)] = notes
    assert flds == "What is a CTE?\x1fA named subquery."
    assert "ankigen::weak_card" in tags and f"ankigen::run_{RUN_DATE}" in tags


def test_export_guid_is_stable(wh, tmp_path):
    _kept(wh, [("u1", "DS::SQL", "What is a CTE?", "A named subquery.")])
    export.run(wh, RUN_DATE, tmp_path / "a")
    export.run(wh, RUN_DATE, tmp_path / "b")
    guid_a = _notes_in(tmp_path / "a" / str(RUN_DATE) / f"ankigen_{RUN_DATE}.apkg")[1][0][0]
    guid_b = _notes_in(tmp_path / "b" / str(RUN_DATE) / f"ankigen_{RUN_DATE}.apkg")[1][0][0]
    assert guid_a == guid_b                     # reimporting updates instead of duplicating


def test_rerun_with_nothing_kept_removes_stale_package(wh, tmp_path):
    _kept(wh, [("u1", "DS::SQL", "What is a CTE?", "A named subquery.")])
    export.run(wh, RUN_DATE, tmp_path / "out")
    wh.replace_partition("dedup_results", RUN_DATE, ("run_date", "card_uid", "is_dup", "reason", "similarity"),
                         [(RUN_DATE, "u1", True, "dup", 0.99)])
    assert export.run(wh, RUN_DATE, tmp_path / "out")["apkg"] is None
    assert not (tmp_path / "out" / str(RUN_DATE) / f"ankigen_{RUN_DATE}.apkg").exists()


def test_unverified_cards_are_tagged(wh, tmp_path):
    _kept(wh, [("u1", "DS::SQL", "Q?", "A.")])
    wh.con.execute("UPDATE verified_cards SET reason = 'unverified: 429'")
    export.run(wh, RUN_DATE, tmp_path / "out")
    tags = _notes_in(tmp_path / "out" / str(RUN_DATE) / f"ankigen_{RUN_DATE}.apkg")[1][0][2]
    assert "ankigen::unverified" in tags
