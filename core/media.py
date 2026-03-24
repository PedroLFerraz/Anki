import logging
import os
import re
import tempfile
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from gtts import gTTS
from duckduckgo_search import DDGS
from urllib.parse import urlparse

from core.config import MEDIA_DIR

logger = logging.getLogger(__name__)


# --- 1. SEARCH ENGINES ---

def search_wikimedia(query: str) -> list[str]:
    """Primary search for art/history images via Wikimedia Commons."""
    url = "https://commons.wikimedia.org/w/api.php"
    clean_query = query.replace("painting", "").strip()

    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": f"{clean_query} filetype:bitmap",
        "gsrlimit": 3,
        "prop": "imageinfo",
        "iiprop": "url",
    }

    headers = {
        "User-Agent": "AnkiCardGenerator/2.0 (https://github.com/anki-generator)"
    }

    candidates = []
    try:
        if random.random() > 0.7:
            time.sleep(0.1)

        res = requests.get(url, params=params, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            pages = data.get("query", {}).get("pages", {})
            for page_id in pages:
                image_info = pages[page_id].get("imageinfo", [])
                if image_info:
                    candidates.append(image_info[0]["url"])
        else:
            logger.warning("Wikimedia status error: %s", res.status_code)
    except Exception as e:
        logger.warning("Wikimedia connection error: %s", e)

    return candidates


def search_duckduckgo(query: str) -> list[str]:
    """Secondary search with exponential backoff."""
    candidates = []
    max_retries = 3

    for attempt in range(max_retries):
        try:
            wait_time = (2**attempt) + random.uniform(0, 1)
            time.sleep(wait_time)

            with DDGS() as ddgs:
                results = list(
                    ddgs.images(
                        keywords=query, region="wt-wt", safesearch="on", max_results=2
                    )
                )
                if results:
                    candidates = [r["image"] for r in results]
                    return candidates
        except Exception as e:
            logger.warning("DDG attempt %d failed: %s", attempt + 1, e)

    return []


def search_images(query: str) -> list[str]:
    """Master search: Wikimedia first, then DuckDuckGo fallback."""
    candidates = search_wikimedia(query)

    if len(candidates) < 2:
        try:
            ddg_results = search_duckduckgo(query)
            candidates.extend(ddg_results)
        except Exception:
            pass

    return candidates


# --- 2. DOWNLOADER ---

def download_image(urls: list[str] | str) -> tuple[str, bytes] | None:
    """
    Downloads from a list of URLs until one works.
    Returns (filename, raw_bytes) or None.
    """
    if isinstance(urls, str):
        urls = [urls]

    for url in urls:
        try:
            domain = urlparse(url).netloc
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": f"https://{domain}/",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            }

            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                content_type = response.headers.get("Content-Type", "").lower()
                if "image" in content_type:
                    filename = f"web_img_{abs(hash(url))}.jpg"
                    # Save to local media dir
                    filepath = MEDIA_DIR / filename
                    filepath.write_bytes(response.content)
                    return filename, response.content
        except Exception:
            continue

    return None


# --- 3. AUDIO ---

def generate_audio(text: str, lang: str = "en") -> tuple[str, bytes] | None:
    """
    Generates TTS audio. Returns (filename, raw_bytes) or None.
    """
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
            tts = gTTS(text=text, lang=lang)
            tts.save(fp.name)
            temp_path = fp.name

        with open(temp_path, "rb") as f:
            audio_bytes = f.read()
        os.remove(temp_path)

        safe_name = re.sub(r"[^a-zA-Z0-9]", "", text[:10])
        filename = f"audio_{safe_name}_{abs(hash(text))}.mp3"

        filepath = MEDIA_DIR / filename
        filepath.write_bytes(audio_bytes)

        return filename, audio_bytes
    except Exception as e:
        logger.warning("Audio generation error: %s", e)
        return None


# --- 4. BATCH OPERATIONS ---

def _fetch_single_image(card_id: int, search_query: str) -> tuple[int, str | None]:
    """Search + download image for a single card. Returns (card_id, filename)."""
    try:
        urls = search_images(search_query)
        if urls:
            result = download_image(urls)
            if result:
                return card_id, result[0]
    except Exception as e:
        logger.warning("Image fetch failed for card %d: %s", card_id, e)
    return card_id, None


def fetch_images_batch(
    tasks: list[tuple[int, str]],
    max_workers: int = 3,
    on_progress: callable = None,
) -> dict[int, str | None]:
    """
    Fetch images for multiple cards in parallel.

    Args:
        tasks: list of (card_id, search_query) tuples
        max_workers: number of parallel downloads (keep low to avoid rate limits)
        on_progress: callback(card_id, filename, done_count, total)

    Returns:
        dict mapping card_id -> filename (or None if failed)
    """
    results = {}
    total = len(tasks)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_single_image, card_id, query): card_id
            for card_id, query in tasks
        }

        for i, future in enumerate(as_completed(futures), 1):
            card_id, filename = future.result()
            results[card_id] = filename
            if on_progress:
                on_progress(card_id, filename, i, total)

    return results
