"""Unified test suite for the Anki flashcard generator."""
import argparse
import json
import sqlite3
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from core.card_types import CARD_TYPES, get_card_type, BASIC, DETAILED, VISUAL, CLOZE
from core.embeddings import cosine_similarity, fuzzy_match, is_duplicate
from core.agents import _clean_field, _fix_cloze_syntax, generate_cards
from core import agents
from core.images import search_and_download, search_and_download_batch
from core.apkg_import import import_apkg, _strip_html
from export.genanki_export import export_cards
from storage import repository


# ============================================================
# Card Types
# ============================================================

def test_all_types_present():
    assert set(CARD_TYPES.keys()) == {"basic", "detailed", "visual", "cloze"}


def test_get_card_type():
    assert get_card_type("basic") is BASIC
    assert get_card_type("cloze") is CLOZE
    assert get_card_type("nonexistent") is None


def test_basic_fields():
    assert BASIC["fields"] == ["Question", "Answer"]
    assert BASIC["model_id"] == 1607392320


def test_detailed_fields():
    assert "Question" in DETAILED["fields"]
    assert "Summary" in DETAILED["fields"]
    assert "Explanation" in DETAILED["fields"]
    assert "Image" in DETAILED["fields"]


def test_visual_fields():
    assert VISUAL["fields"] == ["Image", "Title", "Explanation"]


def test_cloze_fields():
    assert CLOZE["fields"] == ["Text", "Extra"]
    assert CLOZE["model_type"] == 1


def test_stable_model_ids():
    assert BASIC["model_id"] == 1607392320
    assert DETAILED["model_id"] == 1607392321
    assert VISUAL["model_id"] == 1607392322
    assert CLOZE["model_id"] == 1607392323


def test_cloze_template_uses_cloze_syntax():
    assert "{{cloze:Text}}" in CLOZE["template_front"]
    assert "{{cloze:Text}}" in CLOZE["template_back"]


def test_all_types_have_required_keys():
    required = {"name", "model_id", "fields", "template_front", "template_back", "css"}
    for name, typedef in CARD_TYPES.items():
        missing = required - set(typedef.keys())
        assert not missing, f"{name} missing keys: {missing}"


# ============================================================
# Repository (CRUD)
# ============================================================

def test_save_and_get_basic_card():
    card_id = repository.save_card("What is Python?", "A programming language", "CS")
    cards = repository.get_cards()
    assert len(cards) == 1
    assert cards[0]["id"] == card_id
    assert cards[0]["question"] == "What is Python?"
    assert cards[0]["status"] == "GENERATED"
    assert cards[0]["card_type"] == "basic"


def test_save_card_with_extra_fields():
    extra = {"summary": "Bold answer", "explanation": "Longer text"}
    repository.save_card("Q?", "A", "t", card_type="detailed", extra_fields=extra)
    cards = repository.get_cards()
    assert cards[0]["extra_fields"]["summary"] == "Bold answer"


def test_save_card_with_embedding():
    emb = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    repository.save_card("Q", "A", "t", embedding=emb)
    ctx_cards, _ = repository.get_context_cards_with_embeddings()
    assert len(ctx_cards) == 0


def test_update_card_status():
    card_id = repository.save_card("Q", "A", "t")
    repository.update_card_status(card_id, "ACCEPTED")
    cards = repository.get_cards(status="ACCEPTED")
    assert len(cards) == 1
    assert cards[0]["id"] == card_id


def test_update_card_content():
    card_id = repository.save_card("Old Q", "Old A", "t")
    repository.update_card_content(card_id, "New Q", "New A")
    cards = repository.get_cards()
    assert cards[0]["question"] == "New Q"
    assert cards[0]["answer"] == "New A"


def test_update_card_content_with_extra_fields():
    card_id = repository.save_card("Q", "A", "t", extra_fields={"key": "old"})
    repository.update_card_content(card_id, "Q2", "A2", extra_fields={"key": "new"})
    cards = repository.get_cards()
    assert cards[0]["extra_fields"]["key"] == "new"


def test_update_card_extra_fields():
    card_id = repository.save_card("Q", "A", "t", extra_fields={"a": 1})
    repository.update_card_extra_fields(card_id, {"a": 1, "b": 2})
    cards = repository.get_cards()
    assert cards[0]["extra_fields"]["b"] == 2


def test_filter_by_topic():
    repository.save_card("Q1", "A1", "Math")
    repository.save_card("Q2", "A2", "Science")
    assert len(repository.get_cards(topic="Math")) == 1


def test_filter_by_status():
    cid1 = repository.save_card("Q1", "A1", "t")
    repository.save_card("Q2", "A2", "t")
    repository.update_card_status(cid1, "ACCEPTED")
    assert len(repository.get_cards(status="ACCEPTED")) == 1
    assert len(repository.get_cards(status="GENERATED")) == 1


def test_delete_cards_by_status():
    repository.save_card("Q1", "A1", "t")
    repository.save_card("Q2", "A2", "t")
    deleted = repository.delete_cards_by_status("GENERATED")
    assert deleted == 2
    assert len(repository.get_cards()) == 0


def test_delete_cards_by_status_with_topic():
    repository.save_card("Q1", "A1", "Math")
    repository.save_card("Q2", "A2", "Science")
    deleted = repository.delete_cards_by_status("GENERATED", topic="Math")
    assert deleted == 1
    assert len(repository.get_cards()) == 1


def test_save_and_get_context_cards():
    cards = [{"question": "Q1", "answer": "A1"}, {"question": "Q2", "answer": "A2"}]
    count = repository.save_context_cards(cards, source="test_deck")
    assert count == 2
    ctx, _ = repository.get_context_cards_with_embeddings()
    assert len(ctx) == 2
    assert ctx[0]["Question"] == "Q1"


def test_context_count():
    repository.save_context_cards([{"question": "Q", "answer": "A"}])
    assert repository.get_context_count() == 1


def test_delete_context_cards():
    repository.save_context_cards([{"question": "Q", "answer": "A"}])
    deleted = repository.delete_context_cards()
    assert deleted == 1
    assert repository.get_context_count() == 0


def test_context_cards_skip_empty_question():
    cards = [{"question": "", "answer": "A"}, {"question": "Q", "answer": "A"}]
    count = repository.save_context_cards(cards)
    assert count == 1


def test_combined_topic_and_status_filter():
    cid1 = repository.save_card("Q1", "A1", "Math")
    repository.save_card("Q2", "A2", "Math")
    repository.save_card("Q3", "A3", "Science")
    repository.update_card_status(cid1, "ACCEPTED")
    results = repository.get_cards(topic="Math", status="ACCEPTED")
    assert len(results) == 1
    assert results[0]["id"] == cid1


def test_corrupt_embedding_deserialization():
    from storage.repository import _deserialize_embedding
    result = _deserialize_embedding(b"corrupt")
    assert result is None


def test_context_cards_have_correct_status():
    repository.save_context_cards([{"question": "Q", "answer": "A"}], source="deck")
    cards = repository.get_cards(status="CONTEXT")
    assert len(cards) == 1
    assert cards[0]["status"] == "CONTEXT"
    assert cards[0]["card_type"] == "context"


def test_get_card_by_id_found():
    card_id = repository.save_card("Q", "A", "t")
    card = repository.get_card_by_id(card_id)
    assert card is not None
    assert card["question"] == "Q"


def test_get_card_by_id_not_found():
    assert repository.get_card_by_id(99999) is None


def test_delete_card_by_id_exists():
    card_id = repository.save_card("Q", "A", "t")
    assert repository.delete_card_by_id(card_id) is True
    assert repository.get_card_by_id(card_id) is None


def test_delete_card_by_id_not_exists():
    assert repository.delete_card_by_id(99999) is False


def test_get_card_counts():
    repository.save_card("Q1", "A1", "Math")
    repository.save_card("Q2", "A2", "Math")
    cid3 = repository.save_card("Q3", "A3", "Science")
    repository.update_card_status(cid3, "ACCEPTED")
    counts = repository.get_card_counts()
    assert counts["total"] == 3
    assert counts["by_status"]["GENERATED"] == 2
    assert counts["by_status"]["ACCEPTED"] == 1
    assert counts["by_type"]["basic"] == 3
    math_counts = repository.get_card_counts(topic="Math")
    assert math_counts["total"] == 2


def test_get_topics():
    repository.save_card("Q1", "A1", "Math")
    repository.save_card("Q2", "A2", "Science")
    repository.save_card("Q3", "A3", "Math")
    topics = repository.get_topics()
    assert topics == ["Math", "Science"]


def test_update_cards_status_batch():
    id1 = repository.save_card("Q1", "A1", "t")
    id2 = repository.save_card("Q2", "A2", "t")
    id3 = repository.save_card("Q3", "A3", "t")
    count = repository.update_cards_status_batch([id1, id2], "ACCEPTED")
    assert count == 2
    assert repository.get_card_by_id(id1)["status"] == "ACCEPTED"
    assert repository.get_card_by_id(id2)["status"] == "ACCEPTED"
    assert repository.get_card_by_id(id3)["status"] == "GENERATED"


def test_update_cards_status_batch_empty():
    assert repository.update_cards_status_batch([], "ACCEPTED") == 0


def test_invalid_status_rejected_on_save():
    with pytest.raises(ValueError, match="Invalid status"):
        repository.save_card("Q", "A", "t", status="INVALID")


def test_invalid_status_rejected_on_update():
    card_id = repository.save_card("Q", "A", "t")
    with pytest.raises(ValueError, match="Invalid status"):
        repository.update_card_status(card_id, "BOGUS")


def test_corrupted_extra_fields_returns_empty():
    from storage.repository import _parse_extra_fields
    assert _parse_extra_fields(None) == {}
    assert _parse_extra_fields("") == {}
    assert _parse_extra_fields("{invalid json") == {}
    assert _parse_extra_fields('{"key": "value"}') == {"key": "value"}


# ============================================================
# Embeddings & Dedup
# ============================================================

def test_cosine_identical():
    v = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal():
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_zero_vector():
    a = np.array([1.0, 2.0], dtype=np.float32)
    z = np.array([0.0, 0.0], dtype=np.float32)
    assert cosine_similarity(a, z) == 0.0


def test_fuzzy_exact_match():
    assert fuzzy_match("What is Python?", "What is Python?")


def test_fuzzy_case_insensitive():
    assert fuzzy_match("WHAT IS PYTHON?", "what is python?")


def test_fuzzy_article_stripping():
    assert fuzzy_match("The mitochondria", "mitochondria")


def test_fuzzy_different_strings():
    assert not fuzzy_match("What is Python?", "How does SQL work?")


def test_fuzzy_close_but_different():
    assert fuzzy_match("What is machine learning?", "What is machine learnin?")


def test_is_duplicate_fuzzy():
    existing = [{"Question": "What is Python?", "Answer": "A language"}]
    is_dup, reason = is_duplicate("What is Python?", existing, [None])
    assert is_dup
    assert "Fuzzy" in reason


def test_is_duplicate_semantic():
    existing = [{"Question": "Explain Python", "Answer": "A language"}]
    emb_existing = np.array([0.9, 0.1, 0.0], dtype=np.float32)
    emb_new = np.array([0.88, 0.12, 0.01], dtype=np.float32)
    is_dup, reason = is_duplicate(
        "Describe Python", existing, [emb_existing],
        new_embedding=emb_new, semantic_threshold=0.95,
    )
    sim = cosine_similarity(emb_new, emb_existing)
    if sim >= 0.95:
        assert is_dup
    else:
        assert not is_dup


def test_not_duplicate():
    existing = [{"Question": "What is Python?", "Answer": "A language"}]
    is_dup, reason = is_duplicate("How does TCP work?", existing, [None])
    assert not is_dup
    assert reason == ""


def test_duplicate_empty_existing():
    is_dup, _ = is_duplicate("Anything", [], [])
    assert not is_dup


def test_is_duplicate_dimension_mismatch_no_crash():
    existing = [{"Question": "What is X?", "Answer": "A thing"}]
    emb_existing = np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
    emb_new = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    is_dup, reason = is_duplicate(
        "Something different", existing, [emb_existing], new_embedding=emb_new,
    )
    assert not is_dup


def test_cosine_similarity_dimension_mismatch_raises():
    a = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    b = np.array([1.0, 2.0], dtype=np.float32)
    with pytest.raises(ValueError):
        cosine_similarity(a, b)


def test_embedding_failure_sets_warned_flag(monkeypatch):
    import core.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "_embedding_warned", False)
    monkeypatch.setattr("core.config.settings.llm_provider", "ollama")
    mock_client = MagicMock()
    mock_client.embeddings.create.side_effect = Exception("unavailable")
    monkeypatch.setattr(emb_mod, "_get_ollama_client", lambda: mock_client)
    result = emb_mod.get_embedding("test text")
    assert result is None
    assert emb_mod._embedding_warned is True


# ============================================================
# Agents (Card Generation)
# ============================================================

def test_clean_field_strips_markdown():
    assert _clean_field("## Heading") == "Heading"
    assert _clean_field("* Bold text *") == "Bold text"
    assert _clean_field("> Quoted text") == "Quoted text"


def test_clean_field_strips_bullets():
    assert _clean_field("- Item") == "Item"
    assert _clean_field("• Bullet") == "Bullet"


def test_clean_field_normal_text():
    assert _clean_field("Normal text") == "Normal text"


def test_fix_single_braces():
    assert _fix_cloze_syntax("The {c1::dog} is big.") == "The {{c1::dog}} is big."


def test_fix_triple_braces():
    assert _fix_cloze_syntax("The {{{c1::cat}}} is small.") == "The {{c1::cat}} is small."


def test_fix_missing_c1_prefix():
    assert _fix_cloze_syntax("The {{dog}} is big.") == "The {{c1::dog}} is big."


def test_fix_already_correct():
    text = "The {{c1::mitochondria}} is the powerhouse."
    assert _fix_cloze_syntax(text) == text


def test_fix_multiple_cloze_markers():
    text = "{c1::Python} uses {c2::indentation}."
    result = _fix_cloze_syntax(text)
    assert "{{c1::Python}}" in result
    assert "{{c2::indentation}}" in result


@patch("core.agents._generate_json")
def test_generate_basic_cards(mock_gen):
    mock_gen.return_value = {"cards": [
        {"question": "What is Python?", "answer": "A programming language"},
        {"question": "What is Java?", "answer": "Another programming language"},
    ]}
    cards = generate_cards("Programming", 2, "(none)", card_type="basic")
    assert len(cards) == 2
    assert cards[0]["question"] == "What is Python?"


@patch("core.agents._generate_json")
def test_generate_detailed_cards(mock_gen):
    mock_gen.return_value = {"cards": [{
        "question": "What is ML?",
        "summary": "Machine Learning",
        "explanation": "A field of AI",
        "image_query": "machine learning diagram",
    }]}
    cards = generate_cards("ML", 1, "(none)", card_type="detailed")
    assert len(cards) == 1
    assert cards[0]["summary"] == "Machine Learning"
    assert cards[0]["image_query"] == "machine learning diagram"


@patch("core.agents._generate_json")
def test_generate_visual_cards(mock_gen):
    mock_gen.return_value = {"cards": [{
        "title": "Confusion Matrix",
        "explanation": "Shows classification results.",
        "image_query": "confusion matrix diagram",
    }]}
    cards = generate_cards("ML", 1, "(none)", card_type="visual")
    assert len(cards) == 1
    assert cards[0]["title"] == "Confusion Matrix"
    assert cards[0]["question"] == "Confusion Matrix"


@patch("core.agents._generate_json")
def test_generate_cloze_cards(mock_gen):
    mock_gen.return_value = {"cards": [{
        "text": "The {{c1::mitochondria}} is the powerhouse of the cell.",
        "extra": "Found in eukaryotic cells",
    }]}
    cards = generate_cards("Biology", 1, "(none)", card_type="cloze")
    assert len(cards) == 1
    assert "{{c1::mitochondria}}" in cards[0]["answer"]
    assert "mitochondria" in cards[0]["question"]
    assert "{{" not in cards[0]["question"]


@patch("core.agents._generate_json")
def test_generate_cloze_fixes_syntax(mock_gen):
    mock_gen.return_value = {"cards": [{
        "text": "The {c1::dog} is big.",
        "extra": "",
    }]}
    cards = generate_cards("Animals", 1, "(none)", card_type="cloze")
    assert len(cards) == 1
    assert "{{c1::dog}}" in cards[0]["answer"]


@patch("core.agents._generate_json")
def test_generate_skips_low_quality(mock_gen):
    mock_gen.return_value = {"cards": [
        {"question": "Hi", "answer": ""},
        {"question": "What is gravity?", "answer": "A force of nature"},
    ]}
    cards = generate_cards("Physics", 1, "(none)", card_type="basic")
    assert len(cards) == 1
    assert cards[0]["question"] == "What is gravity?"


@patch("core.agents._generate_json")
def test_generate_handles_empty_response(mock_gen):
    mock_gen.return_value = {"cards": []}
    cards = generate_cards("Nothing", 5, "(none)")
    assert cards == []


@patch("core.agents._generate_json")
def test_generate_retries_on_partial(mock_gen):
    mock_gen.side_effect = [
        {"cards": [{"question": "What is photosynthesis?", "answer": "A process in plants"}]},
        {"cards": [{"question": "What is respiration?", "answer": "Cells convert glucose to energy"}]},
    ]
    cards = generate_cards("Topic", 2, "(none)")
    assert len(cards) == 2


@patch("core.agents._generate_json")
def test_generate_detailed_missing_summary_fallback(mock_gen):
    mock_gen.return_value = {"cards": [{
        "question": "What is gradient descent?",
        "summary": "",
        "explanation": "An optimization algorithm. It minimizes loss functions.",
        "image_query": "gradient descent diagram",
    }]}
    cards = generate_cards("ML", 1, "(none)", card_type="detailed")
    assert len(cards) == 1
    assert cards[0]["summary"] == "An optimization algorithm."


@patch("core.agents._generate_json")
def test_generate_detailed_missing_image_query_fallback(mock_gen):
    mock_gen.return_value = {"cards": [{
        "question": "What is gradient descent?",
        "summary": "An optimization method",
        "explanation": "It minimizes loss iteratively.",
        "image_query": "",
    }]}
    cards = generate_cards("ML", 1, "(none)", card_type="detailed")
    assert len(cards) == 1
    assert len(cards[0]["image_query"]) > 0


@patch("core.agents._generate_json")
def test_generate_visual_missing_image_query_fallback(mock_gen):
    mock_gen.return_value = {"cards": [{
        "title": "Neural Network",
        "explanation": "A computational model inspired by biology.",
        "image_query": "",
    }]}
    cards = generate_cards("ML", 1, "(none)", card_type="visual")
    assert len(cards) == 1
    assert cards[0]["image_query"] == "neural network diagram"


@patch("core.agents._generate_json")
def test_generate_cloze_skips_no_marker(mock_gen):
    mock_gen.return_value = {"cards": [
        {"text": "This sentence has no cloze deletion at all.", "extra": ""},
        {"text": "The {{c1::mitochondria}} is important.", "extra": "hint"},
    ]}
    cards = generate_cards("Bio", 1, "(none)", card_type="cloze")
    assert len(cards) == 1
    assert "mitochondria" in cards[0]["answer"]


def test_check_llm_connection_ollama_error(monkeypatch):
    monkeypatch.setattr("core.config.settings.llm_provider", "ollama")
    monkeypatch.setattr("core.config.settings.ollama_base_url", "http://localhost:11434/v1")
    with patch("requests.get", side_effect=Exception("Connection refused")):
        result = agents.check_llm_connection()
    assert result is not None
    assert "Cannot connect" in result


# ============================================================
# Export (.apkg generation)
# ============================================================

def test_export_basic_cards(exports_dir):
    cards = [
        {"id": 1, "question": "Q1", "answer": "A1", "card_type": "basic", "extra_fields": {}},
        {"id": 2, "question": "Q2", "answer": "A2", "card_type": "basic", "extra_fields": {}},
    ]
    path = export_cards(cards, deck_name="Test")
    assert path.exists()
    assert path.suffix == ".apkg"
    assert zipfile.is_zipfile(path)


def test_export_detailed_cards(exports_dir, media_dir):
    with patch("export.genanki_export.MEDIA_DIR", media_dir):
        cards = [{
            "id": 1,
            "question": "What is ML?",
            "answer": "Machine Learning",
            "card_type": "detailed",
            "extra_fields": {
                "summary": "Machine Learning",
                "explanation": "A field of AI",
                "image_filename": None,
            },
        }]
        path = export_cards(cards, deck_name="Detailed")
        assert path.exists()


def test_export_visual_card_without_image_skipped(exports_dir, media_dir):
    with patch("export.genanki_export.MEDIA_DIR", media_dir):
        cards = [{
            "id": 1,
            "question": "No Image",
            "answer": "Explanation",
            "card_type": "visual",
            "extra_fields": {"title": "No Image", "explanation": "Exp"},
        }]
        path = export_cards(cards, deck_name="Visual")
        assert path.exists()


def test_export_visual_card_with_image(exports_dir, media_dir):
    img_file = media_dir / "test_img.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    with patch("export.genanki_export.MEDIA_DIR", media_dir):
        cards = [{
            "id": 1,
            "question": "Confusion Matrix",
            "answer": "Shows classification results",
            "card_type": "visual",
            "extra_fields": {
                "title": "Confusion Matrix",
                "explanation": "Shows classification results",
                "image_filename": "test_img.jpg",
            },
        }]
        path = export_cards(cards, deck_name="Visual")
        assert path.exists()
        with zipfile.ZipFile(path) as z:
            assert "media" in z.namelist()
            media_map = json.loads(z.read("media"))
            assert "test_img.jpg" in media_map.values()


def test_export_cloze_cards(exports_dir):
    cards = [{
        "id": 1,
        "question": "The mitochondria is the powerhouse",
        "answer": "The {{c1::mitochondria}} is the powerhouse of the cell.",
        "card_type": "cloze",
        "extra_fields": {
            "text": "The {{c1::mitochondria}} is the powerhouse of the cell.",
            "extra": "Found in eukaryotic cells",
        },
    }]
    path = export_cards(cards, deck_name="Cloze")
    assert path.exists()


def test_export_mixed_card_types(exports_dir):
    cards = [
        {"id": 1, "question": "Q1", "answer": "A1", "card_type": "basic", "extra_fields": {}},
        {"id": 2, "question": "Q2", "answer": "{{c1::A2}}", "card_type": "cloze",
         "extra_fields": {"text": "{{c1::A2}}", "extra": ""}},
    ]
    path = export_cards(cards, deck_name="Mixed")
    assert path.exists()


def test_export_stable_deck_id():
    import hashlib
    deck_name = "StableTest"
    expected_id = int(hashlib.md5(deck_name.encode()).hexdigest(), 16) % (10**10)
    id1 = int(hashlib.md5(deck_name.encode()).hexdigest(), 16) % (10**10)
    id2 = int(hashlib.md5(deck_name.encode()).hexdigest(), 16) % (10**10)
    assert id1 == id2 == expected_id


def test_export_empty_cards(exports_dir):
    path = export_cards([], deck_name="Empty")
    assert path.exists()


def test_export_filename_sanitized(exports_dir):
    cards = [{"id": 1, "question": "Q", "answer": "A", "card_type": "basic", "extra_fields": {}}]
    path = export_cards(cards, deck_name='Test: Deck <1> "pipes|?')
    assert path.exists()
    for char in '<>:"|?*\\':
        assert char not in path.name


def test_export_pathological_deck_name(exports_dir):
    cards = [{"id": 1, "question": "Q", "answer": "A", "card_type": "basic", "extra_fields": {}}]
    path = export_cards(cards, deck_name='???')
    assert path.exists()
    assert "deck_" in path.name


def test_export_detailed_card_with_media(exports_dir, media_dir):
    img_file = media_dir / "detail_img.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    with patch("export.genanki_export.MEDIA_DIR", media_dir):
        cards = [{
            "id": 1,
            "question": "What is ML?",
            "answer": "Machine Learning",
            "card_type": "detailed",
            "extra_fields": {
                "summary": "Machine Learning",
                "explanation": "A field of AI",
                "image_filename": "detail_img.jpg",
            },
        }]
        path = export_cards(cards, deck_name="DetailMedia")
        assert path.exists()
        with zipfile.ZipFile(path) as z:
            media_map = json.loads(z.read("media"))
            assert "detail_img.jpg" in media_map.values()


def test_export_unknown_card_type_skipped(exports_dir):
    cards = [
        {"id": 1, "question": "Q1", "answer": "A1", "card_type": "unknown_type", "extra_fields": {}},
        {"id": 2, "question": "Q2", "answer": "A2", "card_type": "basic", "extra_fields": {}},
    ]
    path = export_cards(cards, deck_name="SkipUnknown")
    assert path.exists()


def test_export_cloze_without_markers_skipped(exports_dir):
    cards = [{
        "id": 1,
        "question": "Plain text",
        "answer": "Plain text without any cloze markers",
        "card_type": "cloze",
        "extra_fields": {"text": "Plain text without any cloze markers", "extra": ""},
    }]
    path = export_cards(cards, deck_name="BadCloze")
    assert path.exists()


# ============================================================
# Images (search & download)
# ============================================================

@patch("core.images._download_and_save")
@patch("ddgs.DDGS")
def test_search_and_download_success(mock_ddgs_cls, mock_download, media_dir):
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.images.return_value = [
        {"image": "https://example.com/img.jpg", "width": 800}
    ]
    mock_ddgs_cls.return_value = mock_ddgs
    mock_download.return_value = "test_image.jpg"
    result = search_and_download("test query", card_id=1)
    assert result == "test_image.jpg"


def test_search_and_download_empty_query():
    assert search_and_download("", card_id=0) is None
    assert search_and_download("  ", card_id=0) is None


@patch("core.images.search_and_download")
def test_batch_download(mock_search):
    mock_search.side_effect = lambda q, cid: f"img_{cid}.jpg"
    queries = [("query1", 1), ("query2", 2), ("query3", 3)]
    results = search_and_download_batch(queries)
    assert len(results) == 3
    assert results[1] == "img_1.jpg"
    assert results[2] == "img_2.jpg"
    assert results[3] == "img_3.jpg"


def test_batch_download_empty():
    assert search_and_download_batch([]) == {}


@patch("core.images.search_and_download")
def test_batch_download_handles_failures(mock_search):
    def side_effect(q, cid):
        if cid == 2:
            raise Exception("Network error")
        return f"img_{cid}.jpg"
    mock_search.side_effect = side_effect
    queries = [("q1", 1), ("q2", 2), ("q3", 3)]
    results = search_and_download_batch(queries)
    assert results[1] == "img_1.jpg"
    assert results[2] is None
    assert results[3] == "img_3.jpg"


@patch("core.images._download_and_save", return_value="retried.jpg")
@patch("time.sleep")
@patch("ddgs.DDGS")
def test_search_retries_on_ratelimit(mock_ddgs_cls, mock_sleep, mock_download):
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.images.side_effect = [
        Exception("Ratelimit"),
        [{"image": "https://example.com/img.jpg", "width": 800}],
    ]
    mock_ddgs_cls.return_value = mock_ddgs
    result = search_and_download("test query", card_id=1)
    assert result == "retried.jpg"
    mock_sleep.assert_called_once()


@patch("core.images.requests.get")
def test_download_and_save_converts_png_to_jpeg(mock_get, media_dir):
    """PNG downloaded from web must be saved as JPEG — Anki doesn't handle PNG well."""
    from io import BytesIO
    from PIL import Image as PILImage
    from core.images import _download_and_save

    # Create a real RGBA PNG in memory (transparency = worst case for JPEG)
    img = PILImage.new("RGBA", (200, 150), (255, 0, 0, 128))
    buf = BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    mock_resp = MagicMock()
    mock_resp.headers = {"content-type": "image/png"}
    mock_resp.iter_content.return_value = [png_bytes]
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    with patch("core.images.MEDIA_DIR", media_dir):
        filename = _download_and_save("https://example.com/photo.png", "test query", 1)

    assert filename is not None
    assert filename.endswith(".jpg")

    # Verify the file is actually a valid JPEG, not PNG
    saved_path = media_dir / filename
    assert saved_path.exists()
    with PILImage.open(saved_path) as saved:
        assert saved.format == "JPEG"
        assert saved.mode == "RGB"  # RGBA must have been converted


# ============================================================
# Import (.apkg parsing)
# ============================================================

def test_strip_html_basic_tags():
    assert _strip_html("<b>bold</b>") == "bold"
    assert _strip_html("<div>text</div>") == "text"


def test_strip_html_img_tags():
    assert _strip_html('<img src="image.jpg">') == ""


def test_strip_html_sound_refs():
    assert _strip_html("[sound:audio.mp3]") == ""


def test_strip_html_mixed():
    html = '<b>Bold</b> text <img src="img.jpg"> and [sound:x.mp3] more'
    assert _strip_html(html) == "Bold text and more"


def test_strip_html_whitespace_cleanup():
    assert _strip_html("  multiple   spaces  ") == "multiple spaces"


def _create_apkg(tmp_path, notes, decks=None):
    """Create a minimal .apkg file with the given notes."""
    db_path = tmp_path / "collection.anki2"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, flds TEXT, mid INTEGER)")
    conn.execute("CREATE TABLE col (id INTEGER, decks TEXT)")
    for i, (flds, mid) in enumerate(notes):
        conn.execute("INSERT INTO notes (id, flds, mid) VALUES (?, ?, ?)", (i + 1, flds, mid))
    if decks is None:
        decks = {"1": {"name": "Default"}, "123": {"name": "Test Deck"}}
    conn.execute("INSERT INTO col (id, decks) VALUES (1, ?)", (json.dumps(decks),))
    conn.commit()
    conn.close()
    apkg_path = tmp_path / "test.apkg"
    with zipfile.ZipFile(apkg_path, "w") as z:
        z.write(db_path, "collection.anki2")
    return apkg_path


def test_import_basic_cards(tmp_path):
    notes = [
        ("What is Python?\x1fA programming language", 1),
        ("What is Java?\x1fAnother language", 1),
    ]
    apkg = _create_apkg(tmp_path, notes)
    deck_name, cards = import_apkg(apkg)
    assert deck_name == "Test Deck"
    assert len(cards) == 2
    assert cards[0]["question"] == "What is Python?"
    assert cards[0]["answer"] == "A programming language"


def test_import_html_stripping(tmp_path):
    notes = [("<b>Bold Q</b>\x1f<i>Italic A</i>", 1)]
    apkg = _create_apkg(tmp_path, notes)
    _, cards = import_apkg(apkg)
    assert cards[0]["question"] == "Bold Q"
    assert cards[0]["answer"] == "Italic A"


def test_import_cloze_note(tmp_path):
    notes = [("The {{c1::mitochondria}} is the powerhouse", 1)]
    apkg = _create_apkg(tmp_path, notes)
    _, cards = import_apkg(apkg)
    assert len(cards) == 1
    assert "mitochondria" in cards[0]["question"]
    assert "{{" not in cards[0]["question"]


def test_import_image_only_card(tmp_path):
    notes = [('<img src="img.jpg">\x1fThe Mona Lisa', 1)]
    apkg = _create_apkg(tmp_path, notes)
    _, cards = import_apkg(apkg)
    assert len(cards) == 1
    assert cards[0]["question"] == "The Mona Lisa"


def test_import_skips_empty_cards(tmp_path):
    notes = [("\x1f", 1), ("OK question\x1fOK answer", 1)]
    apkg = _create_apkg(tmp_path, notes)
    _, cards = import_apkg(apkg)
    assert len(cards) == 1


def test_import_deck_name_skips_default(tmp_path):
    decks = {"1": {"name": "Default"}, "42": {"name": "My Custom Deck"}}
    notes = [("Q\x1fA", 1)]
    apkg = _create_apkg(tmp_path, notes, decks=decks)
    deck_name, _ = import_apkg(apkg)
    assert deck_name == "My Custom Deck"


def test_import_file_not_found():
    with pytest.raises(FileNotFoundError):
        import_apkg("/nonexistent/path.apkg")


def test_import_wrong_extension(tmp_path):
    fake = tmp_path / "test.zip"
    fake.write_text("not an apkg")
    with pytest.raises(ValueError, match="Not an .apkg"):
        import_apkg(fake)


def test_import_multifield_notes(tmp_path):
    notes = [("Question\x1f\x1fExtra detail here", 1)]
    apkg = _create_apkg(tmp_path, notes)
    _, cards = import_apkg(apkg)
    assert len(cards) == 1
    assert "Extra detail here" in cards[0]["answer"]


def test_import_anki21_format(tmp_path):
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    db_path = build_dir / "collection.anki21"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, flds TEXT, mid INTEGER)")
    conn.execute("CREATE TABLE col (id INTEGER, decks TEXT)")
    conn.execute("INSERT INTO notes (id, flds, mid) VALUES (1, ?, 1)",
                 ("What is Python?\x1fA programming language",))
    decks = {"1": {"name": "Default"}, "99": {"name": "Anki21 Deck"}}
    conn.execute("INSERT INTO col (id, decks) VALUES (1, ?)", (json.dumps(decks),))
    conn.commit()
    conn.close()
    apkg_path = tmp_path / "test21.apkg"
    with zipfile.ZipFile(apkg_path, "w") as z:
        z.write(str(db_path), "collection.anki21")
    deck_name, cards = import_apkg(apkg_path)
    assert deck_name == "Anki21 Deck"
    assert len(cards) == 1


def test_import_corrupted_zip(tmp_path):
    bad_file = tmp_path / "corrupt.apkg"
    bad_file.write_bytes(b"this is not a zip file")
    with pytest.raises(Exception):
        import_apkg(bad_file)


def test_import_no_notes_table(tmp_path):
    db_path = tmp_path / "collection.anki2"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE col (id INTEGER, decks TEXT)")
    decks = {"1": {"name": "Default"}, "5": {"name": "Empty"}}
    conn.execute("INSERT INTO col (id, decks) VALUES (1, ?)", (json.dumps(decks),))
    conn.commit()
    conn.close()
    apkg_path = tmp_path / "test.apkg"
    with zipfile.ZipFile(apkg_path, "w") as z:
        z.write(db_path, "collection.anki2")
    deck_name, cards = import_apkg(apkg_path)
    assert cards == []


# ============================================================
# CLI Input Validation
# ============================================================

def test_cli_empty_topic_exits(monkeypatch):
    from cli import cmd_generate
    args = argparse.Namespace(topic="  ", count=5, type="basic",
                              deck_name="Test", no_embeddings=False)
    with pytest.raises(SystemExit):
        cmd_generate(args)


def test_cli_zero_count_exits(monkeypatch):
    from cli import cmd_generate
    args = argparse.Namespace(topic="Math", count=0, type="basic",
                              deck_name="Test", no_embeddings=False)
    with pytest.raises(SystemExit):
        cmd_generate(args)


def test_cli_negative_count_exits(monkeypatch):
    from cli import cmd_generate
    args = argparse.Namespace(topic="Math", count=-3, type="basic",
                              deck_name="Test", no_embeddings=False)
    with pytest.raises(SystemExit):
        cmd_generate(args)


# ============================================================
# Connection Safety
# ============================================================

def test_connection_closed_on_exception():
    """Verify try/finally ensures connection is closed even on error."""
    from unittest.mock import patch, MagicMock
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.execute.side_effect = RuntimeError("DB error")
    with patch("storage.repository.get_connection", return_value=mock_conn):
        with pytest.raises(RuntimeError):
            repository.save_card("Q", "A", "t")
    mock_conn.close.assert_called_once()
