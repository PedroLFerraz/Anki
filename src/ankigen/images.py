"""Find and store an illustration for a card.

Two sources, tried in order:

1. **DuckDuckGo** — broad coverage, but it rate-limits aggressively and returns
   ordinary web images. Fine for private study cards.
2. **Wikimedia Commons** — a documented API with openly licensed media. Thinner
   coverage for tooling topics, but it answers when DuckDuckGo throttles.

Everything is saved as JPEG. Anki imports JPEG reliably; PNG and WebP caused
import problems in v1, so conversion is unconditional rather than best-effort.
"""
from __future__ import annotations

import hashlib
import logging
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
USER_AGENT = "AnkiGen/2.1 (personal flashcard generator)"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"


@dataclass
class ImageResult:
    card_uid: str
    query: str
    filename: str | None = None
    source: str | None = None       # "duckduckgo" | "wikimedia" | "cached"
    detail: str = ""                # why it failed, when it did

    @property
    def found(self) -> bool:
        return self.filename is not None


# ----------------------------------------------------------------- search

def search_duckduckgo(query: str, limit: int = 5) -> list[str]:
    from ddgs import DDGS

    for attempt in range(3):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.images(query, max_results=limit))
            return [
                r["image"] for r in results
                if r.get("image") and (r.get("width") or 0) >= MIN_SOURCE_WIDTH
            ]
        except Exception as e:
            if "ratelimit" in str(e).lower() and attempt < 2:
                wait = 5 * (attempt + 1)
                logger.info("DuckDuckGo rate limited; waiting %ds", wait)
                time.sleep(wait)
                continue
            logger.info("DuckDuckGo search failed for %r: %s", query, e)
            return []
    return []


def search_wikimedia(query: str, limit: int = 5) -> list[str]:
    """Openly licensed images, via the Commons search API."""
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": limit,
        "prop": "imageinfo", "iiprop": "url|size", "iiurlwidth": MAX_WIDTH,
    }
    try:
        resp = requests.get(COMMONS_API, params=params,
                            headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        resp.raise_for_status()
        pages = (resp.json().get("query") or {}).get("pages") or {}
    except Exception as e:
        logger.info("Wikimedia search failed for %r: %s", query, e)
        return []

    urls = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        # thumburl is already resized; falling back to the full-size original.
        url = info.get("thumburl") or info.get("url")
        if url and (info.get("width") or MIN_SOURCE_WIDTH) >= MIN_SOURCE_WIDTH:
            urls.append(url)
    return urls


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


def fetch(card_uid: str, query: str, media_dir: Path) -> ImageResult:
    """First usable image for a query, DuckDuckGo first then Wikimedia."""
    if not query or len(query.strip()) < 3:
        return ImageResult(card_uid, query, detail="no image query")

    for source, search in (("duckduckgo", search_duckduckgo), ("wikimedia", search_wikimedia)):
        for url in search(query):
            name = download_as_jpeg(url, query, media_dir)
            if name:
                return ImageResult(card_uid, query, filename=name, source=source)
        logger.info("No usable image from %s for %r", source, query)
    return ImageResult(card_uid, query, detail="no usable image from either source")


def fetch_many(jobs: list[tuple[str, str]], media_dir: Path, workers: int = 3) -> list[ImageResult]:
    """Fetch concurrently, but gently — DuckDuckGo throttles parallel callers."""
    if not jobs:
        return []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fetch, uid, query, media_dir) for uid, query in jobs]
        results = []
        for (uid, query), future in zip(jobs, futures):
            try:
                results.append(future.result())
            except Exception as e:                      # never let one image kill the stage
                results.append(ImageResult(uid, query, detail=str(e)))
    return results
