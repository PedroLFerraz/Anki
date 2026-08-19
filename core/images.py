"""Image search and download via DuckDuckGo."""
from __future__ import annotations

import hashlib
import logging
import re

import requests
from PIL import Image

from core.config import MEDIA_DIR

logger = logging.getLogger(__name__)

MAX_WIDTH = 800
TIMEOUT = 10


def search_and_download_batch(queries: list[tuple[str, int]]) -> dict[int, str | None]:
    """Download images concurrently. Takes list of (query, card_id) pairs.
    Returns {card_id: filename_or_None}.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = {}
    if not queries:
        return results

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(search_and_download, query, card_id): card_id
            for query, card_id in queries
        }
        for future in as_completed(futures):
            card_id = futures[future]
            try:
                results[card_id] = future.result()
            except Exception:
                results[card_id] = None

    return results


def search_and_download(query: str, card_id: int = 0) -> str | None:
    """Search DuckDuckGo for images and download the first suitable one.

    Returns the filename (relative to MEDIA_DIR) or None.
    Retries with backoff on rate limits.
    """
    import time

    if not query or len(query.strip()) < 2:
        return None

    for attempt in range(3):
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.images(query, max_results=5))

            for r in results:
                url = r.get("image", "")
                width = r.get("width", 0)

                if not url or width < 200:
                    continue

                filename = _download_and_save(url, query, card_id)
                if filename:
                    return filename

            logger.info("No suitable images found for: %s", query)
            return None

        except Exception as e:
            if "Ratelimit" in str(e) and attempt < 2:
                wait = (attempt + 1) * 5
                logger.info("Rate limited, waiting %ds before retry...", wait)
                time.sleep(wait)
                continue
            logger.warning("Image search failed for '%s': %s", query, e)
            return None

    return None


def _download_and_save(url: str, query: str, card_id: int) -> str | None:
    """Download an image, resize if needed, save to MEDIA_DIR."""
    try:
        resp = requests.get(url, timeout=TIMEOUT, stream=True,
                            headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "image" not in content_type:
            return None

        # Always save as JPEG for Anki compatibility
        slug = re.sub(r"[^a-z0-9]+", "_", query.lower().strip())[:30]
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        filename = f"{slug}_{card_id}_{url_hash}.jpg"
        filepath = MEDIA_DIR / filename

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)

        # Convert to JPEG and resize if needed
        try:
            with Image.open(filepath) as img:
                if img.mode in ('RGBA', 'P', 'LA', 'L'):
                    img = img.convert('RGB')
                if img.width > MAX_WIDTH:
                    ratio = MAX_WIDTH / img.width
                    new_size = (MAX_WIDTH, int(img.height * ratio))
                    img = img.resize(new_size, Image.LANCZOS)
                img.save(filepath, "JPEG")
        except Exception as e:
            logger.warning("Could not convert to JPEG %s: %s", filename, e)
            filepath.unlink(missing_ok=True)
            return None

        logger.info("Downloaded image: %s", filename)
        return filename

    except Exception as e:
        logger.warning("Image download failed from %s: %s", url[:60], e)
        return None
