from datetime import date, timedelta

import pytest
from pydantic import ValidationError
from conftest import RUN_DATE

from ankigen.ingest import read_notes
from ankigen.profile import Profile, load_profile
from ankigen.targeting import LEGACY_INBOX, build_requests, in_deck, nearest


# ------------------------------------------------------------------ profile

def test_profile_loads_and_normalises_deck(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text("decks:\n  - deck: ' DS :: SQL '\n    topics: [joins]\n", encoding="utf-8")
    assert load_profile(p).decks[0].deck == "DS::SQL"


def test_unquoted_colon_in_yaml_is_a_clear_error(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text("learner:\n  goals:\n    - Interviews: SQL and stats\ndecks: []\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="goals"):
        load_profile(p)


def test_validate_against_collection(profile):
    assert profile.validate_against({"DS::SQL", "Deutsch"}) == []          # new_deck is allowed
    problems = profile.validate_against({"Deutsch"})
    assert any("DS::SQL" in p for p in problems)


def test_new_deck_without_topics_is_rejected():
    p = Profile.model_validate({"decks": [{"deck": "X", "new_deck": True}]})
    assert "needs `topics:`" in p.validate_against(set())[0]


def test_subdeck_counts_as_existing(profile):
    assert profile.validate_against({"DS::SQL::Advanced"}) == []


# ------------------------------------------------------------------ targeting

@pytest.fixture
def notes(modern_collection):
    return read_notes(modern_collection)


def test_in_deck_covers_subdecks_and_inbox():
    assert in_deck("DS::SQL", "DS::SQL")
    assert in_deck("DS::SQL::Advanced", "DS::SQL")
    assert in_deck(f"{LEGACY_INBOX}::DS::SQL", "DS::SQL")   # exported by v2.0
    assert not in_deck("DS::SQLite", "DS::SQL")


def test_same_date_same_requests(profile, notes):
    a = build_requests(profile, notes, RUN_DATE)
    b = build_requests(profile, notes, RUN_DATE)
    assert [(r.request_id, r.prompt) for r in a] == [(r.request_id, r.prompt) for r in b]


def test_topics_rotate_across_days(profile, notes):
    topics = {
        r.topic
        for d in range(3)
        for r in build_requests(profile, notes, RUN_DATE + timedelta(days=d))
        if r.deck == "DS::SQL" and r.reason == "topic"
    }
    assert topics == {"joins", "indexes", "NULLs"}


def test_quotas_respected(profile, notes):
    reqs = build_requests(profile, notes, RUN_DATE)
    assert sum(r.n for r in reqs if r.deck == "DS::SQL") == 4
    assert sum(r.n for r in reqs if r.deck == "Data Platform::Airflow") == 2
    profile.global_quota = 3
    assert sum(r.n for r in build_requests(profile, notes, RUN_DATE)) == 3


def test_weak_card_gets_its_own_request(profile, notes):
    weak = [r for r in build_requests(profile, notes, RUN_DATE) if r.reason == "weak_card"]
    assert len(weak) == 1
    assert "What is a CTE?" in weak[0].focus           # lapses=3, ease=1900
    assert "different angle" in weak[0].prompt


def test_new_deck_borrows_style_from_other_targeted_decks(profile, notes):
    req = next(r for r in build_requests(profile, notes, RUN_DATE) if r.deck == "Data Platform::Airflow")
    assert req.style_examples                        # nothing of its own to imitate
    assert "(nothing yet" in req.prompt


def test_gap_request_when_no_topics(notes):
    p = Profile.model_validate({"decks": [{"deck": "DS::SQL", "daily_quota": 2}],
                                "weak_cards": {"enabled": False}})
    [req] = build_requests(p, notes, RUN_DATE)
    assert req.reason == "gap" and req.n == 2


def test_prompt_is_personalised(profile, notes):
    req = next(r for r in build_requests(profile, notes, RUN_DATE)
               if r.deck == "DS::SQL" and r.reason == "topic")
    assert "Use backticks for SQL." in req.prompt              # deck instructions
    assert "Be concise." in req.prompt                          # style rules
    assert "interviews" in req.prompt                           # learner goals
    assert "Q: " in req.prompt                                  # few-shot examples
    assert '{"cards": [{"question"' in req.prompt               # format contract


def test_nearest_ignores_unrelated_cards(notes):
    sql = [n for n in notes if n.deck.startswith("DS::SQL")]
    assert nearest("window functions over partitions", sql, 10) == [
        "How do window functions differ from GROUP BY?"
    ]
