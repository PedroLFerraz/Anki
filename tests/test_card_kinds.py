"""Cards shaped by what they teach, a curriculum in levels, and a kickoff day."""
import json
from datetime import date

import pytest
from pydantic import ValidationError

from ankigen import generate
from ankigen.card_types import CARD_TYPES
from ankigen.generate import html_text, parse_kind
from ankigen.profile import DeckTarget, Profile
from ankigen.targeting import KIND_NOTE, LEVELS, ad_hoc_request, build_requests

LEVELS_YAML = {
    1: [{"concept": "what the terminal and the shell are"},
        {"command": "moving around: pwd, cd, ls"},
        {"shortcut": "terminal shortcuts: Tab, Ctrl+C, Ctrl+R"},
        {"build": "a first Dockerfile"}],
    4: [{"scenario": "stopping a container: SIGTERM and SIGKILL"}],
}


def _profile(**deck):
    return Profile.model_validate({"global_quota": 20, "decks": [{
        "deck": "DP::Linux", "new_deck": True, "start": "2026-10-01", "daily_quota": 20,
        "levels": LEVELS_YAML, **deck}]})


# ------------------------------------------------------------ the profile

def test_levels_become_the_ordered_topic_list():
    target = _profile().decks[0]
    assert target.topics[0] == "what the terminal and the shell are"
    assert target.topics[-1] == "stopping a container: SIGTERM and SIGKILL"
    assert target.kind_of("moving around: pwd, cd, ls") == ("command", 1)
    assert target.kind_of("stopping a container: SIGTERM and SIGKILL") == ("scenario", 4)
    assert target.kind_of("not in the plan") == (None, None)


def test_an_unknown_kind_or_level_is_refused():
    with pytest.raises(ValidationError):
        DeckTarget.model_validate({"deck": "X", "levels": {1: [{"essay": "something"}]}})
    with pytest.raises(ValidationError, match="1 to 4"):
        DeckTarget.model_validate({"deck": "X", "levels": {5: [{"concept": "something"}]}})


def test_topics_and_levels_together_are_refused_unless_they_agree():
    with pytest.raises(ValidationError, match="not both"):
        DeckTarget.model_validate({"deck": "X", "topics": ["other"],
                                   "levels": {1: [{"concept": "a"}]}})
    written_back = _profile().decks[0].model_dump()        # carries both
    assert DeckTarget.model_validate(written_back).topics == _profile().decks[0].topics


# ------------------------------------------------------------ planning

def test_each_topic_is_asked_for_in_its_own_shape():
    reqs = build_requests(_profile(), [], date(2026, 10, 1))
    assert [(r.kind, r.level, r.card_type) for r in reqs] == [
        ("concept", 1, "basic"), ("command", 1, "command"),
        ("shortcut", 1, "command"), ("build", 1, "cloze")]
    concept, command, _, build = reqs
    assert "Never name the command" in command.prompt
    assert "with exactly 5 parts hidden" in build.prompt and "Never hide a name" in build.prompt
    assert (build.n, build.parts, build.cards) == (1, 5, 5)   # one note, five gaps
    assert LEVELS[1] in concept.prompt and "Short beats complete" in concept.prompt
    assert "Answers are at most" not in concept.prompt     # the old, longer rules


def test_only_concepts_and_scenarios_may_ask_for_a_picture():
    reqs = build_requests(_profile(), [], date(2026, 10, 1))
    by_kind = {r.kind: r.prompt for r in reqs}
    assert '"image_query"' in by_kind["concept"]
    assert '"image_query"' not in by_kind["command"] and '"image_query"' not in by_kind["build"]


def test_a_plain_topics_deck_is_written_as_before():
    p = Profile.model_validate({"decks": [{"deck": "DS::SQL", "card_type": "detailed",
                                           "topics": ["joins"], "daily_quota": 3}]})
    [req] = build_requests(p, [], date(2026, 10, 1))
    assert (req.kind, req.level, req.card_type) == (None, None, "detailed")
    assert '"summary"' in req.prompt


def test_a_manual_run_on_a_curriculum_topic_keeps_its_kind():
    [req] = ad_hoc_request(_profile(), [], date(2026, 10, 1), "DP::Linux",
                           topic="moving around: pwd, cd, ls")
    assert (req.kind, req.card_type) == ("command", "command")


# ------------------------------------------------------------ the kickoff

def test_the_kickoff_day_lays_down_many_topics_then_the_daily_pace_follows():
    p = Profile.model_validate({"global_quota": 20, "decks": [{
        "deck": "A", "new_deck": True, "start": "2026-10-01", "daily_quota": 20,
        "first_day_quota": 100, "topics": [f"t{i}" for i in range(30)]}]})
    first = build_requests(p, [], date(2026, 10, 1))
    assert sum(r.n for r in first) == 100 and len(first) == 20
    second = build_requests(p, [], date(2026, 10, 2))
    assert [r.topic for r in second] == ["t20", "t21", "t22", "t23"]
    assert p.decks[0].last_day == date(2026, 10, 4)        # 20 + 4 + 4 + 2
    assert p.schedule_problems() == []


def test_the_kickoff_only_raises_the_budget_on_its_own_day():
    p = Profile.model_validate({"global_quota": 20, "decks": [{
        "deck": "A", "new_deck": True, "start": "2026-10-01", "daily_quota": 20,
        "first_day_quota": 100, "topics": ["t"] * 0 + [f"t{i}" for i in range(40)]}]})
    assert p.budget_on(date(2026, 10, 1)) == 100
    assert p.budget_on(date(2026, 10, 2)) == 20


# ------------------------------------------------------------ reading the answers

def test_a_command_card_is_escaped_and_shown_as_code():
    [card] = parse_kind("command", {"cards": [
        {"task": "Follow one service's log", "answer": "journalctl -u <unit> -f", "note": ""}]})
    assert card.fields["Command"] == "<code>journalctl -u &lt;unit&gt; -f</code>"
    assert card.front == "Follow one service's log"


def test_placeholders_survive_in_every_kind():
    """Unescaped, `<service-name>` reached phones as nothing at all."""
    assert html_text("run `ls <dir>` & see") == "run <code>ls &lt;dir&gt;</code> &amp; see"
    [legacy] = generate.parse_cards("basic", {"cards": [
        {"question": "Follow a unit's log?", "answer": "`journalctl -u <unit> -f`"}]})
    assert "&lt;unit&gt;" in legacy.fields["Answer"]


DOCKERFILE = "FROM python:3.12-slim\nCOPY main.py .\nCMD [\"python\", \"main.py\"]"


def test_a_snippet_is_one_note_with_a_gap_per_hidden_part():
    """As separate notes the same file five times over looked to dedup like
    five copies of one card, and it kept one."""
    [card] = parse_kind("build", {"cards": [{
        "context": "A `Dockerfile` for `main.py`", "code": DOCKERFILE,
        "hides": [{"hide": "FROM", "hint": "the starting image"},
                  {"hide": "COPY main.py .", "hint": "puts the script in"},
                  {"hide": "CMD", "hint": ""}]}]})
    text = card.fields["Text"]
    assert text.startswith("A <code>Dockerfile</code> for <code>main.py</code><pre><code>")
    assert ("{{c1::FROM::the starting image}} python:3.12-slim\n"
            "{{c2::COPY main.py .::puts the script in}}\n{{c3::CMD}} [") in text
    assert card.front.endswith('[1] python:3.12-slim\n[2]\n[3] ["python", "main.py"]')
    assert card.back == "[1] FROM; [2] COPY main.py .; [3] CMD"


def test_a_part_that_is_not_in_the_code_is_left_out_but_the_rest_stay():
    [card] = parse_kind("build", {"cards": [{
        "context": "c", "code": DOCKERFILE,
        "hides": [{"hide": "RUN pip install"}, {"hide": "COPY main.py ."}]}]})
    assert "{{c1::COPY main.py .}}" in card.fields["Text"] and "c2::" not in card.fields["Text"]


def test_the_older_one_part_shape_still_reads():
    [card] = parse_kind("build", {"cards": [{
        "context": "c", "code": DOCKERFILE, "hide": "COPY main.py .", "hint": "the script"}]})
    assert "{{c1::COPY main.py .::the script}}" in card.fields["Text"]


@pytest.mark.parametrize("hide", ["COPY other.py .", "", "a::b"])
def test_a_build_card_whose_hidden_part_cannot_be_a_cloze_is_skipped(hide):
    code = "FROM x\nCOPY main.py .\nRUN a::b"
    assert parse_kind("build", {"cards": [{"context": "c", "code": code, "hide": hide}]}) == []


def test_a_scenario_fills_the_detailed_note():
    [card] = parse_kind("scenario", {"cards": [
        {"question": "Why does docker stop take 10 seconds?", "answer": "It waits, then SIGKILL.",
         "why": "SIGTERM was ignored."}]})
    assert set(card.fields) == set(CARD_TYPES["detailed"]["fields"])


def test_every_kind_is_filed_as_a_note_type_that_exists():
    assert set(KIND_NOTE.values()) <= set(CARD_TYPES)


# ------------------------------------------------------------ into Anki

def _command_card():
    return {"card_uid": "u1", "deck": "DP::Linux", "card_type": "command",
            "fields_json": json.dumps({"Task": "Go up one directory",
                                       "Command": "<code>cd ..</code>", "Note": ""}),
            "tags": ["ankigen"], "request_reason": "topic"}


def test_a_command_note_becomes_two_cards_in_a_real_collection(tmp_path):
    pytest.importorskip("anki", reason="the push extra is not installed")
    from anki.collection import Collection

    from ankigen import push

    col = Collection(str(tmp_path / "c.anki2"))
    try:
        result = push.push_cards(col, [_command_card()], tmp_path)
        assert result.added == 1
        assert col.card_count() == 2                       # task to command, and back
        nt = col.models.by_name("AnkiGen Command")
        assert [t["name"] for t in nt["tmpls"]] == ["Task to command", "Command to task"]
    finally:
        col.close()


def test_the_package_carries_both_templates(tmp_path):
    from ankigen.export import build_package
    package = build_package(date(2026, 10, 1), [_command_card()])
    [model] = {n.model for d in package.decks for n in d.notes}
    assert len(model.templates) == 2
