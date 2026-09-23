"""Pushing cards into Anki over AnkiWeb sync.

The collection these touch is a real one belonging to a real person, with
years of review history in it, so the tests here are mostly about what the
code refuses to do.
"""
import pytest

from ankigen import push

pytest.importorskip("anki", reason="the push extra is not installed")

from anki.sync_pb2 import SyncCollectionResponse as Response  # noqa: E402


class _Col:
    """Just enough collection to drive sync and add_note."""

    def __init__(self, required=Response.NORMAL_SYNC, existing=()):
        self.required = required
        self.existing = set(existing)
        self.added = []
        self.uploads = []
        self.db = self
        self.decks = self
        self.media = self

    # --- sync
    def sync_collection(self, auth, media):
        return Response(required=self.required)

    def full_upload_or_download(self, *, auth, server_usn, upload):
        self.uploads.append(upload)

    # --- collection bits used by push_cards
    def scalar(self, _sql, guid):
        return 1 if guid in self.existing else None

    def id(self, name):
        return 1

    def add_file(self, path):
        return "stored.jpg"

    def new_note(self, notetype):
        class _Note:
            def __init__(self): self.guid = ""; self.tags = []; self.fields = {}
            def __setitem__(self, k, v): self.fields[k] = v
        return _Note()

    def add_note(self, note, deck_id):
        self.added.append(note)


def test_a_one_way_sync_is_refused_rather_than_guessed():
    """Satisfying it means declaring one side the winner, and choosing ours
    would throw away however much review history this copy does not have."""
    for required in (Response.FULL_SYNC, Response.FULL_UPLOAD, Response.FULL_DOWNLOAD):
        with pytest.raises(push.SyncRefused, match="one-way sync"):
            push.sync(_Col(required), auth=None)


def test_an_ordinary_sync_goes_through():
    assert push.sync(_Col(Response.NORMAL_SYNC), auth=None) == "synced"
    assert push.sync(_Col(Response.NO_CHANGES), auth=None) == "already up to date"


def test_a_card_already_in_the_collection_is_not_added_twice(tmp_path, monkeypatch):
    """The GUID is the one the .apkg export uses, so importing the package and
    pushing the same run cannot produce two copies of a card."""
    import genanki

    card = {"card_uid": "u1", "deck": "DS::SQL", "card_type": "basic",
            "fields_json": '{"Question": "Q?", "Answer": "A."}', "tags": ["ankigen"]}
    monkeypatch.setattr(push, "_notetype", lambda col, ct: {"name": "AnkiGen Basic"})

    fresh = _Col()
    assert push.push_cards(fresh, [card], tmp_path).added == 1

    known = _Col(existing={genanki.guid_for("u1")})
    result = push.push_cards(known, [card], tmp_path)
    assert (result.added, result.skipped) == (0, 1)
    assert known.added == []


def test_nothing_is_ever_uploaded_wholesale(tmp_path, monkeypatch):
    """full_upload_or_download exists to fetch a first copy. Called the other
    way it replaces the server's collection with ours."""
    col = _Col()
    monkeypatch.setattr(push, "WORKING_COPY", "anki/test.anki2")
    monkeypatch.setattr("anki.collection.Collection", lambda path: col)
    monkeypatch.setattr(push.settings, "data_dir", str(tmp_path), raising=False)

    push.open_collection(auth="token")
    assert col.uploads == [False]          # downloaded, never uploaded
