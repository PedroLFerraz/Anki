"""What each piece of a command does, under the answer: on new command cards,
in front of the checker, and added to the ones already in the collection."""
import json

import pytest

from ankigen import breakdown, llm
from ankigen.generate import parse_kind, parse_parts, parts_html
from ankigen.verify import _listed

DU = {"task": "List the size of each item here, largest last",
      "answer": "du -sh * | sort -h",
      "note": "",
      "parts": [{"part": "du", "means": "disk usage"},
                {"part": "-s", "means": "one total per item"},
                {"part": "-h", "means": "human-readable sizes: K, M, G"},
                {"part": "*", "means": "every item here"},
                {"part": "| sort -h", "means": "sort by size, K < M < G"}]}


def test_a_command_card_carries_its_breakdown_under_the_answer():
    [card] = parse_kind("command", {"cards": [DU]})
    assert 'class="ankigen-parts"' in card.fields["Note"]
    assert "<code>-s</code>" in card.fields["Note"]
    assert "<code>| sort -h</code>" in card.fields["Note"]
    # The front and back dedup compares are the command alone, as for the
    # notes already in the collection.
    assert card.back == "`du -sh * | sort -h`"


def test_a_card_without_parts_is_as_before():
    [card] = parse_kind("command", {"cards": [{"task": "Go to your home directory",
                                               "answer": "cd", "note": ""}]})
    assert card.fields == {"Task": "Go to your home directory", "Command": "<code>cd</code>",
                           "Note": ""}


def test_parts_are_escaped():
    html = parts_html([("<file>", "the file to read & print")])
    assert "<code>&lt;file&gt;</code>" in html and "&amp;" in html


def test_malformed_parts_are_dropped_not_fatal():
    raw = [{"part": "ls"}, "junk", ["-l", "long listing"], {"part": "", "means": "x"},
           {"part": "-a", "means": "all, hidden files too"}]
    assert parse_parts(raw) == [("-l", "long listing"), ("-a", "all, hidden files too")]
    assert parse_parts("not a list") == []


def test_the_checker_is_shown_the_breakdown():
    [card] = parse_kind("command", {"cards": [DU]})
    listed = _listed(1, {"front": card.front, "back": card.back,
                         "fields_json": json.dumps(card.fields)})
    assert "Parts: `du` = disk usage; `-s` = one total per item" in listed


def test_the_export_and_push_never_write_the_checkers_copy():
    """`_parts` is not a field of the note type."""
    from ankigen.card_types import CARD_TYPES

    [card] = parse_kind("command", {"cards": [DU]})
    assert "_parts" in card.fields
    assert "_parts" not in CARD_TYPES["command"]["fields"]


# ------------------------------------------------------------ the notes already there

anki = pytest.importorskip("anki", reason="the push extra is not installed")


@pytest.fixture
def col(tmp_path):
    from anki.collection import Collection

    from ankigen import push

    c = Collection(str(tmp_path / "collection.anki2"))
    notetype = push._notetype(c, "command")
    deck = c.decks.id("Data Platform::01 Linux")
    for task, command, note in [
        ("List the size of each item here", "<code>du -sh *</code>", ""),
        ("Show hidden files too", "<code>ls -a</code>", "dotfiles"),
    ]:
        n = c.new_note(notetype)
        n["Task"], n["Command"], n["Note"] = task, command, note
        c.add_note(n, deck)
    yield c
    c.close()


class _Writer:
    """Writes a breakdown for every card; the checker faults `ls`."""

    def __init__(self):
        self.prompts = []

    def __call__(self, prompt, max_retries=5, cfg=None):
        self.prompts.append(prompt)
        if "fact-checker" in prompt:
            return llm.LLMResult({"results": [
                {"index": 1, "correct": True, "issue": ""},
                {"index": 2, "correct": False, "issue": "-a is not 'alphabetical'"}]}, "fake")
        return llm.LLMResult({"results": [
            {"index": 1, "parts": [{"part": "du", "means": "disk usage"}]},
            {"index": 2, "parts": [{"part": "-a", "means": "alphabetical"}]}]}, "fake")


def test_older_notes_get_a_checked_breakdown(col, monkeypatch):
    writer = _Writer()
    monkeypatch.setattr(llm, "call_json", writer)

    todo = breakdown.missing(col)
    assert [it.command for it in todo] == ["du -sh *", "ls -a"]
    assert todo[0].deck == "Data Platform::01 Linux"

    items = breakdown.write(todo, "new to Linux")
    assert items[0].parts == [("du", "disk usage")]
    assert items[1].parts is None and "alphabetical" in items[1].issue
    assert breakdown.apply(col, items) == 1

    du = col.get_note(todo[0].nid)
    assert 'class="ankigen-parts"' in du["Note"]
    ls = col.get_note(todo[1].nid)
    assert ls["Note"] == "dotfiles"                 # faulted: left exactly as it was
    # Done once: the next run asks only for the one that was left off.
    assert [it.command for it in breakdown.missing(col)] == ["ls -a"]


def test_an_unchecked_breakdown_is_not_added(col, monkeypatch):
    def writer(prompt, max_retries=5, cfg=None):
        if "fact-checker" in prompt:
            raise RuntimeError("checker down")
        return llm.LLMResult({"results": [{"index": 1, "parts": [["du", "disk usage"]]}]}, "fake")

    monkeypatch.setattr(llm, "call_json", writer)
    items = breakdown.write(breakdown.missing(col)[:1], "new to Linux")
    assert items[0].parts is None and items[0].issue.startswith("unchecked")
    assert breakdown.apply(col, items) == 0


def test_only_the_asked_deck(col):
    assert breakdown.missing(col, "Data Platform::02 Networking") == []
    assert len(breakdown.missing(col, "Data Platform")) == 2
