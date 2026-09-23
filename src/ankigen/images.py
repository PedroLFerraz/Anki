"""Find and store an illustration for a card.

Images come from web search (DuckDuckGo, which falls back to other engines on
its own). Wikimedia Commons used to sit behind it as a second source, and was
removed: its full-text search matches file *descriptions*, so it answers every
query with something, and for software topics that something was reliably a
stock photograph. A card with no picture beats a card with the wrong one.

Search engines match the words around a picture and never the picture itself,
so what comes back is checked by a model before it is used — see `fetch`.

Everything is saved as JPEG. Anki imports JPEG reliably; PNG and WebP caused
import problems in v1, so conversion is unconditional rather than best-effort.
"""
from __future__ import annotations

import hashlib
import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image

logger = logging.getLogger(__name__)

MAX_WIDTH = 800
MIN_SOURCE_WIDTH = 300
TIMEOUT = 15
# Roughly three minutes of patience per query, spread over six tries.
DDG_ATTEMPTS = 6
# How many candidate pictures to actually look at before giving up on a card.
MAX_CHECKS = 3
UNCHECKED = "unchecked"
DDG_BACKOFF_CAP = 60
USER_AGENT = "AnkiGen/2.1 (personal flashcard generator)"


@dataclass
class ImageResult:
    card_uid: str
    query: str
    filename: str | None = None
    source: str | None = None       # "duckduckgo" | "cached"
    detail: str = ""                # why it failed, when it did

    @property
    def found(self) -> bool:
        return self.filename is not None


# ----------------------------------------------------------------- search

def _width(value) -> int:
    """`ddgs` falls back to other engines when DuckDuckGo itself fails, and they
    do not agree on the type of `width`: Bing reports it as a string, which once
    made the comparison below raise and threw away every result."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def search_duckduckgo(query: str, limit: int = 5, attempts: int = DDG_ATTEMPTS) -> list[str]:
    """Image URLs for a query, retried patiently.

    This is by far the better source, so it is worth waiting for: a run is a
    daily batch with nobody watching, and a minute of backoff costs nothing
    against coming back with no picture. Every failure is retried, not only
    rate limits — the search fails in several ways (the engine erroring,
    falling back to another engine, or simply answering with nothing) and none
    of them mean the next attempt will fail too.
    """
    from ddgs import DDGS

    for attempt in range(attempts):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.images(query, max_results=limit))
            urls = [
                r["image"] for r in results
                if r.get("image") and _width(r.get("width")) >= MIN_SOURCE_WIDTH
                and not _looks_like_junk(r.get("image"))
                and not _looks_like_junk(r.get("url"))
            ]
            if urls:
                return urls
            reason = "no results"
        except Exception as e:
            reason = str(e)

        if attempt == attempts - 1:
            logger.info("DuckDuckGo gave nothing for %r after %d attempts (%s)",
                        query, attempts, reason)
            return []
        # Jittered, so parallel workers do not retry in lockstep and look
        # even more like a bot than they already do.
        wait = min(DDG_BACKOFF_CAP, 3 * 2 ** attempt) * (0.7 + random.random() * 0.6)
        logger.info("DuckDuckGo: %s for %r; retrying in %.0fs (%d/%d)",
                    reason[:70], query, wait, attempt + 1, attempts)
        time.sleep(wait)
    return []


# Hosts that reliably serve the wrong picture. Stock libraries watermark
# theirs, and SEO farms republish scraped photos under titles written to match
# whatever was searched for — which is how a card about S3's flat namespace
# ended up illustrated with a basketball player.
_JUNK_HOSTS = (
    "gettyimages.", "shutterstock.", "istockphoto.", "alamy.", "dreamstime.",
    "depositphotos.", "123rf.", "stock.adobe.", "storage.googleapis.com",
)


def _looks_like_junk(url: str) -> bool:
    u = (url or "").lower()
    return any(host in u for host in _JUNK_HOSTS)


# ----------------------------------------------------------------- download

def _filename(query: str, url: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", query.lower().strip())[:40].strip("_")
    return f"{slug}_{hashlib.md5(url.encode()).hexdigest()[:8]}.jpg"


def download_as_jpeg(url: str, query: str, media_dir: Path) -> str | None:
    """Download, convert to JPEG, resize. Returns the filename, or None."""
    target = media_dir / _filename(query, url)
    if target.exists():
        return target.name          # same query+url already fetched on an earlier run

    media_dir.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(url, timeout=TIMEOUT, stream=True,
                            headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        if "image" not in resp.headers.get("content-type", ""):
            return None
        with open(target, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
    except Exception as e:
        logger.info("Download failed for %s: %s", url[:60], e)
        target.unlink(missing_ok=True)
        return None

    try:
        with Image.open(target) as img:
            # JPEG has no alpha channel, and palette images lose colours without this.
            if img.mode in ("RGBA", "P", "LA", "L"):
                img = img.convert("RGB")
            if img.width > MAX_WIDTH:
                height = int(img.height * MAX_WIDTH / img.width)
                img = img.resize((MAX_WIDTH, height), Image.LANCZOS)
            img.save(target, "JPEG", quality=85)
    except Exception as e:
        logger.info("Not a usable image (%s): %s", target.name, e)
        target.unlink(missing_ok=True)
        return None

    return target.name


def fetch(card_uid: str, query: str, media_dir: Path, card: str = "",
          verifier=None, max_checks: int = MAX_CHECKS) -> ImageResult:
    """First *usable* image for a query.

    With a `verifier`, usable means something looked at the picture and said it
    illustrates the card. Nothing short of that works: search results come from
    pages whose text matched the query, and the picture on such a page is
    frequently unrelated to it.
    """
    if not query or len(query.strip()) < 3:
        return ImageResult(card_uid, query, detail="no image query")

    source = "duckduckgo"
    checks = 0
    for url in search_duckduckgo(query):
        name = download_as_jpeg(url, query, media_dir)
        if not name:
            continue
        if not (verifier and card):
            return ImageResult(card_uid, query, filename=name, source=source)
        if checks >= max_checks:
            # Every look costs a request on a metered free tier, so stop rather
            # than work through the whole result page.
            (media_dir / name).unlink(missing_ok=True)
            return ImageResult(card_uid, query,
                               detail=f"no relevant image in the first {checks} checked")
        try:
            keep, shows = verifier((media_dir / name).read_bytes(), card, query)
        except Exception as e:
            logger.info("Cannot check images (%s); keeping %s unchecked", e, name)
            return ImageResult(card_uid, query, filename=name, source=source,
                               detail=f"{UNCHECKED}: {e}")
        checks += 1
        if keep:
            return ImageResult(card_uid, query, filename=name, source=source,
                               detail=f"shows {shows}")
        logger.info("Rejected an image for %r: it shows %s", query, shows)
        (media_dir / name).unlink(missing_ok=True)

    logger.info("No usable image for %r", query)
    return ImageResult(card_uid, query, detail="no usable image found")


def fetch_many(jobs: list[tuple], media_dir: Path, workers: int = 3,
               verifier=None) -> list[ImageResult]:
    """Fetch concurrently, but gently — DuckDuckGo throttles parallel callers."""
    if not jobs:
        return []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # A job is (card_uid, query) or (card_uid, query, card_text).
        jobs = [(j[0], j[1], j[2] if len(j) > 2 else "") for j in jobs]
        futures = [pool.submit(fetch, uid, query, media_dir, card, verifier)
                   for uid, query, card in jobs]
        results = []
        for (uid, query, _card), future in zip(jobs, futures):
            try:
                results.append(future.result())
            except Exception as e:                      # never let one image kill the stage
                results.append(ImageResult(uid, query, detail=str(e)))
    return results
