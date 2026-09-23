"""Image search, download and placement. No network: both sources are faked."""
import io as _io
import json
import sqlite3
import zipfile

import pytest
from conftest import RUN_DATE
from PIL import Image

from ankigen import export, generate, images, pipeline
from ankigen.profile import Profile


def _png_bytes(size=(900, 400), mode="RGBA") -> bytes:
    buf = _io.BytesIO()
    Image.new(mode, size, (200, 30, 30, 255) if mode == "RGBA" else (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


class _Resp:
    def __init__(self, content=b"", content_type="image/png", status=200):
        self.content, self.headers, self.status_code = content, {"content-type": content_type}, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, n):
        yield self.content


# ---------------------------------------------------------------- download

def test_png_is_converted_to_jpeg_and_resized(tmp_path, monkeypatch):
    """Anki imports JPEG reliably; PNG and WebP caused failures in v1."""
    monkeypatch.setattr(images.requests, "get", lambda *a, **k: _Resp(_png_bytes()))
    name = images.download_as_jpeg("https://x/y.png", "kubernetes architecture", tmp_path)
    assert name.endswith(".jpg")
    with Image.open(tmp_path / name) as img:
        assert img.format == "JPEG" and img.mode == "RGB"   # alpha dropped
        assert img.width == images.MAX_WIDTH                # 900 -> 800


def test_same_query_and_url_is_not_downloaded_twice(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(images.requests, "get",
                        lambda *a, **k: (calls.append(1), _Resp(_png_bytes()))[1])
    first = images.download_as_jpeg("https://x/y.png", "airflow dag", tmp_path)
    second = images.download_as_jpeg("https://x/y.png", "airflow dag", tmp_path)
    assert first == second and len(calls) == 1


def test_non_image_responses_leave_nothing_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(images.requests, "get",
                        lambda *a, **k: _Resp(b"<html>404</html>", "text/html"))
    assert images.download_as_jpeg("https://x/y", "q", tmp_path) is None
    assert list(tmp_path.glob("*")) == []


def test_corrupt_image_is_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(images.requests, "get", lambda *a, **k: _Resp(b"not an image"))
    assert images.download_as_jpeg("https://x/y.jpg", "q", tmp_path) is None
    assert list(tmp_path.glob("*")) == []


# ---------------------------------------------------------------- sources

def test_wikimedia_is_used_when_duckduckgo_finds_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "search_duckduckgo", lambda q, limit=5: [])
    monkeypatch.setattr(images, "search_wikimedia", lambda q, limit=5: ["https://commons/x.png"])
    monkeypatch.setattr(images.requests, "get", lambda *a, **k: _Resp(_png_bytes()))
    result = images.fetch("u1", "kubernetes pod lifecycle", tmp_path)
    assert result.found and result.source == "wikimedia"


def test_duckduckgo_wins_when_it_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "search_duckduckgo", lambda q, limit=5: ["https://ddg/x.png"])
    monkeypatch.setattr(images, "search_wikimedia",
                        lambda q, limit=5: pytest.fail("should not reach the fallback"))
    monkeypatch.setattr(images.requests, "get", lambda *a, **k: _Resp(_png_bytes()))
    assert images.fetch("u1", "airflow dag", tmp_path).source == "duckduckgo"


def test_both_sources_failing_is_recorded_not_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "search_duckduckgo", lambda q, limit=5: [])
    monkeypatch.setattr(images, "search_wikimedia", lambda q, limit=5: [])
    result = images.fetch("u1", "something unillustratable", tmp_path)
    assert not result.found and "no usable image" in result.detail


def test_wikimedia_parses_the_api_shape(monkeypatch):
    payload = {"query": {"pages": {"1": {"imageinfo": [{"thumburl": "https://c/thumb.jpg", "width": 800}]},
                                   "2": {"imageinfo": [{"url": "https://c/tiny.jpg", "width": 50}]}}}}

    class R:
        def raise_for_status(self): pass
        def json(self): return payload

    monkeypatch.setattr(images.requests, "get", lambda *a, **k: R())
    assert images.search_wikimedia("q") == ["https://c/thumb.jpg"]   # too-small one dropped


def test_one_failing_job_does_not_sink_the_batch(tmp_path, monkeypatch):
    def flaky(uid, query, media_dir):
        if query == "bad":
            raise RuntimeError("boom")
        return images.ImageResult(uid, query, filename="ok.jpg", source="duckduckgo")

    monkeypatch.setattr(images, "fetch", flaky)
    results = images.fetch_many([("u1", "bad"), ("u2", "good")], tmp_path)
    assert [r.found for r in results] == [False, True]


# ---------------------------------------------------------------- prompt + parsing

def test_image_query_only_requested_when_the_deck_wants_images(profile, modern_collection):
    from ankigen.ingest import read_notes
    from ankigen.targeting import build_requests

    notes = read_notes(modern_collection)
    assert any("image_query" in r.prompt for r in build_requests(profile, notes, RUN_DATE))
    profile.images = False
    assert not any("image_query" in r.prompt for r in build_requests(profile, notes, RUN_DATE))


def test_image_query_is_parsed_and_bounded():
    [card] = generate.parse_cards("basic", {"cards": [
        {"question": "What is a pod?", "answer": "The unit of scheduling.",
         "image_query": "kubernetes pod diagram"}]})
    assert card.image_query == "kubernetes pod diagram"
    # Omitted, empty or absurd queries are treated as "no image".
    [plain] = generate.parse_cards("basic", {"cards": [
        {"question": "What is a pod?", "answer": "The unit of scheduling."}]})
    assert plain.image_query == ""
    # A rambling query is trimmed to something a search engine can match.
    [long] = generate.parse_cards("basic", {"cards": [
        {"question": "What is a pod?", "answer": "x.", "image_query": "word " * 40}]})
    assert long.image_query == "word word word word word word"


def test_image_query_is_part_of_the_json_shape(profile, modern_collection):
    """Asked for in a trailing paragraph, the model answers with the keys the
    shape lists and drops this one."""
    from ankigen.ingest import read_notes
    from ankigen.targeting import build_requests

    req = next(r for r in build_requests(profile, read_notes(modern_collection), RUN_DATE)
               if "image_query" in r.prompt)
    shape = next(line for line in req.prompt.splitlines() if line.startswith('{"cards"'))
    assert '"image_query"' in shape


# ---------------------------------------------------------------- export

def _kept_card(wh, image_filename=None, card_type="basic", fields=None):
    fields = fields or {"Question": "What is a pod?", "Answer": "The unit of scheduling."}
    wh.replace_partition("requests", RUN_DATE,
                         ("run_date", "request_id", "deck", "topic", "card_type", "n", "reason", "focus", "prompt"),
                         [(RUN_DATE, "r1", "Data Platform::Kubernetes", "pods", card_type, 1, "topic", None, "p")])
    wh.replace_partition("generated_cards", RUN_DATE, generate.GENERATED_COLUMNS, [
        (RUN_DATE, "u1", "r1", "Data Platform::Kubernetes", card_type, fields.get("Question", "front"),
         "back", json.dumps(fields), "kubernetes pod diagram", "m", 0, 0)])
    wh.replace_partition("verified_cards", RUN_DATE, ("run_date", "card_uid", "passed", "score", "reason"),
                         [(RUN_DATE, "u1", True, 0.9, "")])
    wh.replace_partition("dedup_results", RUN_DATE,
                         ("run_date", "card_uid", "is_dup", "reason", "similarity"),
                         [(RUN_DATE, "u1", False, None, None)])
    wh.replace_partition("card_images", RUN_DATE,
                         ("run_date", "card_uid", "query", "filename", "source", "detail"),
                         [(RUN_DATE, "u1", "kubernetes pod diagram", image_filename, "duckduckgo", "")])


def _package(apkg):
    with zipfile.ZipFile(apkg) as z:
        names = z.namelist()
        media = json.loads(z.read("media")) if "media" in names else {}
        z.extract("collection.anki2", apkg.parent / "x")
    con = sqlite3.connect(apkg.parent / "x" / "collection.anki2")
    try:
        decks = {d["name"] for d in json.loads(con.execute("SELECT decks FROM col").fetchone()[0]).values()}
        flds = [r[0] for r in con.execute("SELECT flds FROM notes")]
    finally:
        con.close()
    return decks, flds, media


def test_image_is_attached_and_packaged(wh, tmp_path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / "pod.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)
    _kept_card(wh, "pod.jpg")

    result = export.run(wh, RUN_DATE, tmp_path / "out", media_dir=media_dir)
    assert result["images"] == 1
    decks, flds, media = _package(tmp_path / "out" / str(RUN_DATE) / f"ankigen_{RUN_DATE}.apkg")
    assert "Data Platform::Kubernetes" in decks          # the real deck, no inbox
    assert '<img src="pod.jpg">' in flds[0]
    assert "pod.jpg" in media.values()


def test_detailed_cards_use_the_image_field(wh, tmp_path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / "pod.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)
    _kept_card(wh, "pod.jpg", card_type="detailed",
               fields={"Question": "Q?", "Summary": "S", "Explanation": "E", "Image": "", "Reference": ""})
    export.run(wh, RUN_DATE, tmp_path / "out", media_dir=media_dir)
    _, flds, _ = _package(tmp_path / "out" / str(RUN_DATE) / f"ankigen_{RUN_DATE}.apkg")
    parts = flds[0].split("\x1f")
    assert parts[3] == '<img src="pod.jpg">'            # the Image field, not the answer
    assert parts[1] == "S"


def test_missing_media_file_still_exports_the_card(wh, tmp_path):
    """A half-downloaded image must not cost us the card."""
    _kept_card(wh, "vanished.jpg")
    result = export.run(wh, RUN_DATE, tmp_path / "out", media_dir=tmp_path / "media")
    assert result["kept"] == 1 and result["images"] == 0
    _, flds, media = _package(tmp_path / "out" / str(RUN_DATE) / f"ankigen_{RUN_DATE}.apkg")
    assert "<img" not in flds[0] and media == {}


def test_card_without_an_image_exports_normally(wh, tmp_path):
    _kept_card(wh, None)
    export.run(wh, RUN_DATE, tmp_path / "out", media_dir=tmp_path / "media")
    _, flds, media = _package(tmp_path / "out" / str(RUN_DATE) / f"ankigen_{RUN_DATE}.apkg")
    assert "<img" not in flds[0] and media == {}


def test_inbox_subdeck_when_the_profile_asks_for_one(wh, tmp_path):
    _kept_card(wh, None)
    profile = Profile.model_validate({"inbox": "AnkiGen",
                                      "decks": [{"deck": "Data Platform::Kubernetes"}]})
    export.run(wh, RUN_DATE, tmp_path / "out", profile, media_dir=tmp_path / "media")
    decks, _, _ = _package(tmp_path / "out" / str(RUN_DATE) / f"ankigen_{RUN_DATE}.apkg")
    assert "Data Platform::Kubernetes::AnkiGen" in decks


# ---------------------------------------------------------------- stage

def test_images_are_only_fetched_for_surviving_cards(wh, tmp_path, monkeypatch, cfg, profile):
    """Fetching before dedup would download pictures for cards about to be binned."""
    wh.replace_partition("requests", RUN_DATE,
                         ("run_date", "request_id", "deck", "topic", "card_type", "n", "reason", "focus", "prompt"),
                         [(RUN_DATE, "r1", "DS::SQL", "t", "basic", 2, "topic", None, "p")])
    wh.replace_partition("generated_cards", RUN_DATE, generate.GENERATED_COLUMNS, [
        (RUN_DATE, "keep", "r1", "DS::SQL", "basic", "Kept?", "y", "{}", "index diagram", "m", 0, 0),
        (RUN_DATE, "drop", "r1", "DS::SQL", "basic", "Dropped?", "y", "{}", "join diagram", "m", 0, 0)])
    wh.replace_partition("verified_cards", RUN_DATE, ("run_date", "card_uid", "passed", "score", "reason"),
                         [(RUN_DATE, "keep", True, 0.9, ""), (RUN_DATE, "drop", True, 0.9, "")])
    wh.replace_partition("dedup_results", RUN_DATE,
                         ("run_date", "card_uid", "is_dup", "reason", "similarity"),
                         [(RUN_DATE, "keep", False, None, None), (RUN_DATE, "drop", True, "dup", 0.99)])

    asked = []
    monkeypatch.setattr(images, "fetch_many",
                        lambda jobs, media_dir, workers=3: (asked.extend(jobs), [
                            images.ImageResult(u, q, filename="x.jpg", source="duckduckgo") for u, q in jobs])[1])
    ctx = pipeline.Context(cfg, profile, wh)
    result = pipeline.stage_images(ctx, RUN_DATE)
    assert [uid for uid, _ in asked] == ["keep"]
    assert result["found"] == 1 and result["by_source"]["duckduckgo"] == 1


def test_images_stage_skipped_for_decks_that_opt_out(wh, tmp_path, monkeypatch, cfg, profile):
    wh.replace_partition("requests", RUN_DATE,
                         ("run_date", "request_id", "deck", "topic", "card_type", "n", "reason", "focus", "prompt"),
                         [(RUN_DATE, "r1", "DS::SQL", "t", "basic", 1, "topic", None, "p")])
    wh.replace_partition("generated_cards", RUN_DATE, generate.GENERATED_COLUMNS, [
        (RUN_DATE, "u1", "r1", "DS::SQL", "basic", "Q?", "A.", "{}", "index diagram", "m", 0, 0)])
    wh.replace_partition("verified_cards", RUN_DATE, ("run_date", "card_uid", "passed", "score", "reason"),
                         [(RUN_DATE, "u1", True, 0.9, "")])
    wh.replace_partition("dedup_results", RUN_DATE,
                         ("run_date", "card_uid", "is_dup", "reason", "similarity"),
                         [(RUN_DATE, "u1", False, None, None)])
    profile.decks[0].images = False        # DS::SQL opts out
    asked = []
    monkeypatch.setattr(images, "fetch_many",
                        lambda jobs, media_dir, workers=3: (asked.extend(jobs), [])[1])
    result = pipeline.stage_images(pipeline.Context(cfg, profile, wh), RUN_DATE)
    assert result["wanted"] == 0 and asked == []       # nothing requested, nothing downloaded
