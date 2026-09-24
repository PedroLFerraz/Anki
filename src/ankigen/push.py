"""Put the day's cards into Anki itself, over AnkiWeb sync.

AnkiWeb has no API for adding notes. What it has is the sync protocol, which
the official `anki` package speaks, so the way in is to keep a collection of
our own, add notes to it, and sync it up. Your devices then sync down as
usual and the cards are simply there.

The order matters, and it is the whole safety story:

    sync down  ->  add notes  ->  sync up

Syncing down first means our copy is never behind yours, which is what would
otherwise make the server demand a one-way sync. If it demands one anyway we
stop, because the only way to satisfy it is to declare one side the winner,
and picking ours would overwrite however many years of review history with
whatever this copy happens to hold. `full_upload_or_download` is therefore
called in exactly one place: the first ever run, to fetch a copy when we have
none. It is never called with upload=True.

One wrinkle of the protocol: AnkiWeb spreads accounts over several sync hosts
and names the right one on first contact, so every session starts with a
handshake. Going straight to the default host fails a full download with
`400 missing original size`, which is not a hint about anything.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ankigen.card_types import CARD_TYPES
from ankigen.config import settings

logger = logging.getLogger(__name__)

# The working copy. Not your collection: ours, kept in the data directory and
# reconciled with AnkiWeb on every push.
WORKING_COPY = "anki/collection.anki2"


class SyncRefused(RuntimeError):
    """The server wants a one-way sync, which we will not choose for you."""


class NotLoggedIn(RuntimeError):
    """No AnkiWeb credentials configured."""


@dataclass
class PushResult:
    added: int
    skipped: int
    media: int
    decks: list[str]

    def __str__(self) -> str:
        return (f"{self.added} added, {self.skipped} already there, "
                f"{self.media} media file(s), decks: {', '.join(self.decks) or 'none'}")


def _auth():
    """A SyncAuth, from a stored key if there is one, otherwise by logging in."""
    from anki.sync_pb2 import SyncAuth

    endpoint = settings.ankiweb_endpoint or None
    if settings.ankiweb_key:
        return SyncAuth(hkey=settings.ankiweb_key, endpoint=endpoint)
    if not (settings.ankiweb_username and settings.ankiweb_password):
        raise NotLoggedIn(
            "Set ANKIWEB_KEY, or ANKIWEB_USERNAME and ANKIWEB_PASSWORD, to push to AnkiWeb. "
            "`ankigen push --login` trades the password for a key you can store instead."
        )
    from anki.collection import Collection

    scratch = Path(settings.data_dir) / "anki" / "_login.anki2"
    scratch.parent.mkdir(parents=True, exist_ok=True)
    col = Collection(str(scratch))
    try:
        return col.sync_login(settings.ankiweb_username, settings.ankiweb_password, endpoint)
    finally:
        col.close()
        scratch.unlink(missing_ok=True)


def _at(auth, endpoint: str):
    from anki.sync_pb2 import SyncAuth

    if not endpoint or endpoint == auth.endpoint:
        return auth
    logger.info("AnkiWeb redirected us to %s", endpoint)
    return SyncAuth(hkey=auth.hkey, endpoint=endpoint)


def resolve_endpoint(col, auth):
    """Find which sync host this account lives on.

    AnkiWeb spreads accounts over several hosts and tells a client which one
    it belongs to on first contact. Skipping that handshake and going straight
    to the default host fails a full download with `400 missing original
    size`, which says nothing about the real problem.
    """
    return _at(auth, col.sync_status(auth).new_endpoint)


def open_collection(auth=None):
    """Our working copy, downloaded from AnkiWeb the first time.

    Returns the collection and the auth to keep using, which may now point at
    a different host than the one we started with.
    """
    from anki.collection import Collection

    path = Path(settings.data_dir) / WORKING_COPY
    path.parent.mkdir(parents=True, exist_ok=True)
    col = Collection(str(path))
    if auth is None:
        return col, auth

    # "Do we have a copy" is about content, not about the file existing.
    # Opening a path creates an empty collection there, and a failed run once
    # cached that empty file — after which every later run believed it already
    # had your collection and refused to sync against the real one.
    empty = not (col.db.scalar("SELECT COUNT(*) FROM notes") or 0)

    auth = resolve_endpoint(col, auth)
    if empty:
        logger.info("No working copy yet; downloading your collection from AnkiWeb.")
        # The only full transfer this module performs, and only ever downward.
        col.full_upload_or_download(auth=auth, server_usn=None, upload=False)
    return col, auth


def sync(col, auth, media: bool = True) -> tuple[str, object]:
    """Reconcile with AnkiWeb, or refuse to guess. Returns (what happened, auth)."""
    from anki.sync_pb2 import SyncCollectionResponse as Response

    out = col.sync_collection(auth, media)
    if out.new_endpoint:
        auth = _at(auth, out.new_endpoint)
        out = col.sync_collection(auth, media)
    required = out.required
    if required in (Response.FULL_SYNC, Response.FULL_UPLOAD, Response.FULL_DOWNLOAD):
        raise SyncRefused(
            "AnkiWeb wants a one-way sync, which means our copy and yours have "
            "diverged beyond what a normal sync can merge. Resolving it means "
            "choosing which side wins, and choosing ours could discard your "
            "review history — so it is yours to make. Sync from Anki on your "
            "own machine, then delete "
            f"{Path(settings.data_dir) / WORKING_COPY} so the next push starts "
            "from a fresh download."
        )
    state = {Response.NO_CHANGES: "already up to date",
             Response.NORMAL_SYNC: "synced"}.get(required, "synced")
    return state, auth


def _notetype(col, card_type: str):
    """The notetype for one of our card types, created if the collection lacks it."""
    spec = CARD_TYPES[card_type]
    name = f"AnkiGen {card_type.capitalize()}"
    existing = col.models.by_name(name)
    if existing:
        return existing

    logger.info("Creating notetype %r", name)
    is_cloze = spec.get("model_type") == 1
    nt = col.models.new(name)
    if is_cloze:
        nt["type"] = 1
    for fieldname in spec["fields"]:
        col.models.add_field(nt, col.models.new_field(fieldname))
    template = col.models.new_template("Card 1")
    template["qfmt"] = spec["template_front"]
    template["afmt"] = spec["template_back"]
    col.models.add_template(nt, template)
    nt["css"] = spec["css"]
    col.models.add(nt)
    return col.models.by_name(name)


def push_cards(col, cards: list[dict], media_dir: Path, deck_for=None) -> PushResult:
    """Add cards the collection does not already have.

    Identified by the same GUID the .apkg export uses, so a card pushed here
    and a card imported from the package are the same note rather than two.
    """
    import genanki

    added = skipped = media = 0
    decks: set[str] = set()
    for card in cards:
        guid = genanki.guid_for(card["card_uid"])
        if col.db.scalar("SELECT 1 FROM notes WHERE guid = ?", guid):
            skipped += 1
            continue

        deck_name = deck_for(card["deck"]) if deck_for else card["deck"]
        deck_id = col.decks.id(deck_name)          # creates it when missing
        decks.add(deck_name)

        notetype = _notetype(col, card["card_type"])
        note = col.new_note(notetype)
        note.guid = guid
        import json as _json

        values = _json.loads(card["fields_json"])
        filename = card.get("image_filename")
        if filename and (media_dir / filename).exists():
            stored = col.media.add_file(str(media_dir / filename))
            values = _with_image(card["card_type"], values, stored)
            media += 1

        for fieldname in CARD_TYPES[card["card_type"]]["fields"]:
            note[fieldname] = str(values.get(fieldname, ""))
        note.tags = [t for t in card.get("tags", []) if t]

        col.add_note(note, deck_id)
        added += 1

    return PushResult(added, skipped, media, sorted(decks))


def _with_image(card_type: str, values: dict, filename: str) -> dict:
    """Same placement the .apkg export uses, so both routes look alike."""
    from ankigen.export import _with_image as place

    return place(card_type, values, filename)
