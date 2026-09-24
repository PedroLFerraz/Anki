"""Pushing cards into Anki over AnkiWeb sync.

The collection these touch is a real one belonging to a real person, with
years of review history in it, so the tests here are mostly about what the
code refuses to do.
"""
import pytest

from ankigen import push

pytest.importorskip("anki", reason="the push extra is not installed")

from anki.sync_pb2 import SyncAuth, SyncCollectionResponse as Response  # noqa: E402


def _auth(endpoint=""):
    return SyncAuth(hkey="k", endpoint=endpoint)


class _Col:
    """Just enough collection to drive sync and add_note."""

    def __init__(self, required=Response.NORMAL_SYNC, existing=(), endpoint="", note_count=0):
        self.required = required
        self.endpoint = endpoint
        self.note_count = note_count
        self.existing = set(existing)
        self.added = []
        self.uploads = []
        self.db = self
        self.decks = self
        self.media = self

    # --- sync
    def sync_collection(self, auth, media):
        return Response(required=self.required)

    def sync_status(self, auth):
        from anki.sync_pb2 import SyncStatusResponse
        return SyncStatusResponse(required=SyncStatusResponse.NORMAL_SYNC,
                                  new_endpoint=self.endpoint)

    def full_upload_or_download(self, *, auth, server_usn, upload):
        self.uploads.append(upload)

    # --- collection bits used by push_cards
    def scalar(self, sql, guid=None):
        if "COUNT(*) FROM notes" in sql:
            return self.note_count
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
            push.sync(_Col(required), auth=_auth())


def test_an_ordinary_sync_goes_through():
    assert push.sync(_Col(Response.NORMAL_SYNC), _auth())[0] == "synced"
    assert push.sync(_Col(Response.NO_CHANGES), _auth())[0] == "already up to date"


def test_the_account_s_own_sync_host_is_found_before_transferring(tmp_path, monkeypatch):
    """AnkiWeb spreads accounts over hosts; using the default one fails a full
    download with "missing original size", which explains nothing."""
    col = _Col(endpoint="https://sync7.ankiweb.net/")
    monkeypatch.setattr("anki.collection.Collection", lambda path: col)
    monkeypatch.setattr(push.settings, "data_dir", str(tmp_path), raising=False)

    _opened, auth = push.open_collection(_auth())
    assert auth.endpoint == "https://sync7.ankiweb.net/"


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

    push.open_collection(_auth())
    assert col.uploads == [False]          # downloaded, never uploaded


def test_an_empty_working_copy_is_downloaded_again(tmp_path, monkeypatch):
    """A failed run cached an empty collection file; every run after it then
    believed it already had yours."""
    monkeypatch.setattr(push.settings, "data_dir", str(tmp_path), raising=False)

    empty = _Col(note_count=0)
    monkeypatch.setattr("anki.collection.Collection", lambda path: empty)
    push.open_collection(_auth())
    assert empty.uploads == [False]        # noticed it was empty, fetched a copy

    full = _Col(note_count=8346)
    monkeypatch.setattr("anki.collection.Collection", lambda path: full)
    push.open_collection(_auth())
    assert full.uploads == []              # already had one, left it alone
