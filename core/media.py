from __future__ import annotations

import logging
import os
import re
import tempfile
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from gtts import gTTS
from urllib.parse import urlparse, quote

from core.config import MEDIA_DIR

logger = logging.getLogger(__name__)

WIKI_HEADERS = {
    "User-Agent": "AnkiCardGenerator/2.0 (https://github.com/anki-generator)"
}

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}


# --- 1. SEARCH ENGINES (ordered by reliability) ---

def _search_wikipedia_lang(lang: str, queries: list[str]) -> list[str]:
    """Search a specific Wikipedia language edition for painting images."""
    candidates = []
    search_url = f"https://{lang}.wikipedia.org/w/api.php"

    for query in queries:
        try:
            search_params = {
                "action": "query",
                "format": "json",
                "list": "search",
                "srsearch": query,
                "srlimit": 5,
            }
            res = requests.get(search_url, params=search_params, headers=WIKI_HEADERS, timeout=5)
            if res.status_code != 200:
                continue

            results = res.json().get("query", {}).get("search", [])
            if not results:
                continue

            # Get all images from the top results' pages (not just the lead image)
            page_titles = [r["title"] for r in results]
            images_params = {
                "action": "query",
                "format": "json",
                "titles": "|".join(page_titles),
                "prop": "pageimages|images",
                "piprop": "original",
                "pilimit": len(page_titles),
                "imlimit": 20,
            }
            img_res = requests.get(search_url, params=images_params, headers=WIKI_HEADERS, timeout=5)
            if img_res.status_code != 200:
                continue

            pages = img_res.json().get("query", {}).get("pages", {})

            # First pass: get lead images, preferring painting-related pages
            for page_id, page in pages.items():
                page_title = page.get("title", "").lower()
                original = page.get("original", {})
                img_url = original.get("source", "")

                if not img_url or not _is_likely_painting(img_url, page_title):
                    continue

                # Prioritize: page title contains "painting" or the artwork title
                # Deprioritize: page title is just the artist name
                candidates.append(img_url)

            # Second pass: look through page images for painting files
            if not candidates:
                all_image_titles = []
                for page_id, page in pages.items():
                    for img in page.get("images", []):
                        img_title = img.get("title", "")
                        if img_title and _is_likely_painting_filename(img_title):
                            all_image_titles.append(img_title)

                # Resolve image titles to URLs
                if all_image_titles:
                    file_params = {
                        "action": "query",
                        "format": "json",
                        "titles": "|".join(all_image_titles[:10]),
                        "prop": "imageinfo",
                        "iiprop": "url",
                    }
                    file_res = requests.get(
                        "https://commons.wikimedia.org/w/api.php",
                        params=file_params, headers=WIKI_HEADERS, timeout=5
                    )
                    if file_res.status_code == 200:
                        file_pages = file_res.json().get("query", {}).get("pages", {})
                        for fp_id, fp in file_pages.items():
                            ii = fp.get("imageinfo", [])
                            if ii:
                                candidates.append(ii[0]["url"])

            if candidates:
                return candidates

        except Exception as e:
            logger.debug("Wikipedia %s search failed for '%s': %s", lang, query, e)

    return candidates


def search_wikipedia(title: str, artist: str) -> list[str]:
    """
    Search Wikipedia for the painting's article and extract the painting image.
    Tries English first, then Portuguese, Spanish, French, Italian, German.
    """
    queries = []
    if title and artist:
        # Most specific first: look for the painting's own article
        queries.append(f'"{title}" painting {artist}')
        queries.append(f"{title} {artist} painting")
        queries.append(f"{title} ({artist})")
    elif title:
        queries.append(f'"{title}" painting')

    # Try English Wikipedia first
    candidates = _search_wikipedia_lang("en", queries)
    if candidates:
        return candidates

    # Try non-English Wikipedias for non-English titles
    if title:
        non_en_queries = [f"{title} {artist}".strip(), title]
        for lang in ["pt", "es", "fr", "it", "de"]:
            candidates = _search_wikipedia_lang(lang, non_en_queries)
            if candidates:
                return candidates

    return []


def search_wikidata(title: str, artist: str) -> list[str]:
    """
    Query Wikidata for the painting entity and get its image.
    Wikidata has structured data for artworks with direct image links (P18).
    Tries multiple languages and search strategies.
    """
    candidates = []
    if not title:
        return []

    url = "https://www.wikidata.org/w/api.php"

    # Try multiple search queries across languages
    search_queries = []
    if artist:
        search_queries.append(("en", f"{title} {artist}"))
        search_queries.append(("en", title))
        search_queries.append(("pt", f"{title} {artist}"))
        search_queries.append(("pt", title))
        search_queries.append(("es", title))
        search_queries.append(("fr", title))
    else:
        search_queries.append(("en", title))
        search_queries.append(("pt", title))

    for lang, query in search_queries:
        if candidates:
            break
        try:
            params = {
                "action": "wbsearchentities",
                "format": "json",
                "language": lang,
                "search": query,
                "limit": 5,
            }
            res = requests.get(url, params=params, headers=WIKI_HEADERS, timeout=5)
            if res.status_code != 200:
                continue

            entities = res.json().get("search", [])
            if not entities:
                continue

            entity_ids = [e["id"] for e in entities[:5]]
            claims_params = {
                "action": "wbgetentities",
                "format": "json",
                "ids": "|".join(entity_ids),
                "props": "claims",
            }
            claims_res = requests.get(url, params=claims_params, headers=WIKI_HEADERS, timeout=5)
            if claims_res.status_code != 200:
                continue

            # Wikidata entity types that are artworks
            # Q3305213=painting, Q93184=drawing, Q18573970=mural, Q15123870=artwork
            # Q860861=sculpture, Q11060274=print, Q17514=watercolor, Q4502142=visual artwork
            artwork_types = {
                "Q3305213", "Q93184", "Q18573970", "Q15123870",
                "Q860861", "Q11060274", "Q17514", "Q4502142",
            }

            entities_data = claims_res.json().get("entities", {})

            # First pass: only artwork entities
            for eid, entity in entities_data.items():
                claims = entity.get("claims", {})

                # Check P31 (instance of) — only accept artworks
                is_artwork = False
                for p31_claim in claims.get("P31", []):
                    type_id = (p31_claim.get("mainsnak", {}).get("datavalue", {})
                               .get("value", {}).get("id", ""))
                    if type_id in artwork_types:
                        is_artwork = True
                        break

                if is_artwork and "P18" in claims:
                    for claim in claims["P18"]:
                        image_name = claim.get("mainsnak", {}).get("datavalue", {}).get("value", "")
                        if image_name:
                            img_url = _commons_filename_to_url(image_name)
                            if img_url:
                                candidates.append(img_url)

            # Second pass: if no artwork entities found, accept any entity with P18
            # but only if it also has P170 (creator) — likely an artwork
            if not candidates:
                for eid, entity in entities_data.items():
                    claims = entity.get("claims", {})
                    if "P18" in claims and "P170" in claims:
                        for claim in claims["P18"]:
                            image_name = claim.get("mainsnak", {}).get("datavalue", {}).get("value", "")
                            if image_name:
                                img_url = _commons_filename_to_url(image_name)
                                if img_url:
                                    candidates.append(img_url)

        except Exception as e:
            logger.debug("Wikidata search failed for '%s' (%s): %s", query, lang, e)

    return candidates


def _commons_filename_to_url(filename: str) -> str | None:
    """Convert a Wikimedia Commons filename to a direct image URL."""
    try:
        url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "format": "json",
            "titles": f"File:{filename}",
            "prop": "imageinfo",
            "iiprop": "url",
        }
        res = requests.get(url, params=params, headers=WIKI_HEADERS, timeout=5)
        if res.status_code == 200:
            pages = res.json().get("query", {}).get("pages", {})
            for page_id, page in pages.items():
                image_info = page.get("imageinfo", [])
                if image_info:
                    return image_info[0]["url"]
    except Exception:
        pass
    return None


def search_wikimedia(query: str, title: str = "", artist: str = "") -> list[str]:
    """Search Wikimedia Commons directly with art-relevance scoring."""
    url = "https://commons.wikimedia.org/w/api.php"
    clean_query = query.replace("painting", "").replace("artwork", "").strip()

    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": f"{clean_query} painting filetype:bitmap",
        "gsrlimit": 10,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
    }

    # Normalize search terms for matching
    title_words = set(title.lower().split()) if title else set()
    artist_words = set(artist.lower().split()) if artist else set()
    # Remove common short words
    title_words -= {"the", "a", "an", "of", "in", "on", "at", "by", "la", "le", "el", "o", "da", "do", "de"}
    artist_words -= {"de", "da", "do", "van", "von", "di", "del"}

    candidates = []
    try:
        res = requests.get(url, params=params, headers=WIKI_HEADERS, timeout=5)
        if res.status_code == 200:
            data = res.json()
            pages = data.get("query", {}).get("pages", {})

            scored = []
            for page_id in pages:
                page = pages[page_id]
                image_info = page.get("imageinfo", [])
                if not image_info:
                    continue
                url_str = image_info[0]["url"]
                file_title = page.get("title", "").lower()
                filename = url_str.split("/")[-1].lower()

                score = 0
                ext_meta = image_info[0].get("extmetadata", {})
                categories = ext_meta.get("Categories", {}).get("value", "").lower()
                desc = ext_meta.get("ImageDescription", {}).get("value", "").lower()
                all_text = f"{file_title} {categories} {desc} {filename}"

                # Strong positive: filename/title contains the artist name
                if artist_words:
                    artist_match = sum(1 for w in artist_words if w in all_text)
                    score += artist_match * 3

                # Strong positive: filename/title contains the painting title words
                if title_words:
                    title_match = sum(1 for w in title_words if w in all_text)
                    score += title_match * 3

                # Moderate positive: art-related categories
                art_keywords = ["paint", "artwork", "canvas", "oil on", "museum", "gallery",
                                "portrait", "landscape", "fresco", "watercolor", "sculpture",
                                "tempera", "acrylic", "gouache", "pastel"]
                for kw in art_keywords:
                    if kw in all_text:
                        score += 1

                # Strong negative: non-painting content
                bad_keywords = ["photo", "flag", "logo", "icon", "map", "diagram", "chart",
                                "stamp", "coin", "screenshot", "satellite", "aerial"]
                for kw in bad_keywords:
                    if kw in all_text:
                        score -= 5

                scored.append((score, url_str))

            scored.sort(key=lambda x: x[0], reverse=True)
            candidates = [url for _, url in scored]

    except Exception as e:
        logger.debug("Wikimedia search failed: %s", e)

    return candidates


def search_duckduckgo(query: str) -> list[str]:
    """Last resort fallback via DuckDuckGo image search."""
    search_query = f"{query} painting artwork"
    candidates = []

    # Trusted art domains to prioritize
    art_domains = {"wikimedia.org", "wikiart.org", "metmuseum.org", "nga.gov",
                   "artic.edu", "moma.org", "tate.org.uk", "rijksmuseum.nl",
                   "uffizi.it", "louvre.fr", "hermitagemuseum.org", "wga.hu",
                   "wikipedia.org", "googleusercontent.com"}

    try:
        from duckduckgo_search import DDGS
    except ImportError:
        try:
            from ddgs import DDGS
        except ImportError:
            logger.warning("Neither duckduckgo_search nor ddgs package installed")
            return []

    for attempt in range(2):
        try:
            wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
            time.sleep(wait_time)

            with DDGS() as ddgs:
                results = list(
                    ddgs.images(
                        keywords=search_query, region="wt-wt", safesearch="on", max_results=5
                    )
                )
                if results:
                    art_results = []
                    other_results = []
                    for r in results:
                        img_url = r["image"]
                        source = r.get("source", "")
                        domain = urlparse(img_url).netloc.lower()
                        is_art = any(ad in domain or ad in source.lower() for ad in art_domains)
                        if is_art:
                            art_results.append(img_url)
                        else:
                            other_results.append(img_url)
                    candidates = art_results + other_results
                    return candidates
        except Exception as e:
            logger.debug("DDG attempt %d failed: %s", attempt + 1, e)

    return []


def _is_likely_painting(url: str, page_title: str = "") -> bool:
    """Filter out non-painting images (SVGs, tiny icons, etc.)."""
    url_lower = url.lower()
    # Skip SVGs, icons, logos
    if any(ext in url_lower for ext in [".svg", ".gif", ".ico"]):
        return False
    # Skip very small images (thumbnails under 200px)
    match = re.search(r'/(\d+)px-', url_lower)
    if match:
        px = int(match.group(1))
        if px < 200:
            return False
    return True


def _is_likely_painting_filename(file_title: str) -> bool:
    """Check if a Wikipedia image filename looks like a painting."""
    t = file_title.lower()
    # Skip non-image files
    if any(ext in t for ext in [".svg", ".gif", ".ico", ".ogg", ".ogv", ".webm"]):
        return False
    # Skip common non-painting files
    if any(kw in t for kw in ["flag", "logo", "icon", "map", "coat_of_arms",
                               "signature", "commons-logo", "wikidata"]):
        return False
    # Positive signals
    if any(kw in t for kw in ["painting", "canvas", "oil_on", "artwork",
                               "museum", "gallery", "portrait"]):
        return True
    # Accept image files (.jpg, .png) that don't have negative signals
    if any(ext in t for ext in [".jpg", ".jpeg", ".png", ".tif", ".tiff"]):
        return True
    return False


def _google_images_url(title: str, artist: str) -> str:
    """Generate a Google Images search URL for manual lookup."""
    query = f"{title} {artist} painting".strip()
    return f"https://www.google.com/search?tbm=isch&q={quote(query)}"


def search_wikipedia_fairuse(title: str, artist: str) -> list[str]:
    """
    Find fair-use images of copyrighted paintings from Wikipedia articles.

    Many Wikipedia articles about specific paintings include fair-use images
    uploaded to the language-specific Wikipedia (not Commons). These are on
    upload.wikimedia.org/wikipedia/{lang}/ instead of /wikipedia/commons/.
    """
    if not title:
        return []

    candidates = []

    # Build search queries — try painting title, with and without artist
    queries = [title]
    if artist:
        queries.insert(0, f"{title} ({artist})")
        queries.insert(0, f"{title} {artist}")

    title_lower = title.lower()
    artist_lower = artist.lower() if artist else ""

    for lang in ["en", "pt", "es", "fr", "it", "de"]:
        api_url = f"https://{lang}.wikipedia.org/w/api.php"
        for query in queries:
            try:
                # Search for the article
                r = requests.get(api_url, params={
                    "action": "query", "format": "json",
                    "list": "search", "srsearch": query, "srlimit": 3,
                }, headers=WIKI_HEADERS, timeout=8)
                if r.status_code != 200:
                    continue

                results = r.json().get("query", {}).get("search", [])
                if not results:
                    continue

                # Get images from the article pages
                page_titles = [s["title"] for s in results]
                r2 = requests.get(api_url, params={
                    "action": "query", "format": "json",
                    "titles": "|".join(page_titles),
                    "prop": "images", "imlimit": 30,
                }, headers=WIKI_HEADERS, timeout=8)
                if r2.status_code != 200:
                    continue

                pages = r2.json().get("query", {}).get("pages", {})
                image_titles = []
                for page in pages.values():
                    for img in page.get("images", []):
                        fname = img["title"]
                        fname_lower = fname.lower()
                        # Skip non-image files and common icons
                        if not any(ext in fname_lower for ext in [".jpg", ".jpeg", ".png"]):
                            continue
                        if any(skip in fname_lower for skip in [
                            "icon", "logo", "nuvola", "farm-fresh", "wiki", "flag",
                            "crystal", "portal", "commons-", "ambox", "edit-",
                            "question_book", "stub", "disambig", "folder",
                        ]):
                            continue
                        image_titles.append(fname)

                if not image_titles:
                    continue

                # Get image URLs — query the language-specific wiki, not Commons
                r3 = requests.get(api_url, params={
                    "action": "query", "format": "json",
                    "titles": "|".join(image_titles[:15]),
                    "prop": "imageinfo", "iiprop": "url",
                }, headers=WIKI_HEADERS, timeout=8)
                if r3.status_code != 200:
                    continue

                img_pages = r3.json().get("query", {}).get("pages", {})
                for p in img_pages.values():
                    ii = p.get("imageinfo", [{}])[0]
                    url = ii.get("url", "")
                    if not url:
                        continue
                    # Score images: prefer ones with title/artist words in filename
                    fname_lower = url.split("/")[-1].lower()
                    score = 0
                    for word in title_lower.split():
                        if len(word) > 2 and word in fname_lower:
                            score += 2
                    if artist_lower:
                        for word in artist_lower.split():
                            if len(word) > 2 and word in fname_lower:
                                score += 2
                    candidates.append((score, url))

                if candidates:
                    # Return best-scored images
                    candidates.sort(key=lambda x: x[0], reverse=True)
                    return [url for _, url in candidates]

            except Exception as e:
                logger.debug("Wikipedia %s fairuse search failed: %s", lang, e)

    return []


def _score_url_relevance(url: str, title: str, artist: str) -> int:
    """Score a URL by how likely it is to be the actual painting image."""
    fname = url.split("/")[-1].lower().replace("%20", " ").replace("_", " ")
    score = 0
    title_lower = title.lower()
    # Filename contains painting title words = strong signal
    for word in title_lower.split():
        if len(word) > 2 and word in fname:
            score += 3
    # Filename contains artist name = moderate signal (could be artist photo)
    if artist:
        for word in artist.lower().split():
            if len(word) > 2 and word in fname:
                score += 1
    # Penalize if filename looks like a portrait/photo of the artist
    if "portrait" in fname or "photo" in fname or "ca." in fname:
        score -= 3
    return score


def search_images(title: str = "", artist: str = "", query: str = "") -> tuple[list[str], bool]:
    """
    Master image search — tries multiple sources, returns best results.

    Returns (urls, is_verified):
      - urls: list of image URLs, sorted by relevance to the painting
      - is_verified: True if found from a structured/trusted source
    """
    all_candidates = []  # list of (score, url, verified)
    search_text = f"{title} {artist}".strip() if title else query

    if not search_text:
        return [], False

    # Source 1: Wikidata P18 (structured data — free images)
    if title:
        wikidata_results = search_wikidata(title, artist)
        if wikidata_results:
            logger.info("Found %d images via Wikidata for '%s'", len(wikidata_results), search_text)
            for url in wikidata_results:
                score = _score_url_relevance(url, title, artist) + 5  # bonus for Wikidata
                all_candidates.append((score, url, True))

    # Source 2: Wikipedia fair-use images (copyrighted paintings)
    if title:
        fairuse_results = search_wikipedia_fairuse(title, artist)
        if fairuse_results:
            logger.info("Found %d fair-use images via Wikipedia for '%s'", len(fairuse_results), search_text)
            for url in fairuse_results:
                score = _score_url_relevance(url, title, artist) + 5  # bonus for fair-use
                all_candidates.append((score, url, True))

    # Source 3: Wikimedia Commons search
    if len(all_candidates) < 3:
        commons_results = search_wikimedia(search_text, title=title, artist=artist)
        if commons_results:
            logger.info("Found %d images via Wikimedia Commons for '%s'", len(commons_results), search_text)
            for url in commons_results:
                score = _score_url_relevance(url, title, artist)
                all_candidates.append((score, url, False))

    # Source 4: Wikipedia article lead images
    if title and len(all_candidates) < 3:
        wiki_results = search_wikipedia(title, artist)
        if wiki_results:
            logger.info("Found %d images via Wikipedia for '%s'", len(wiki_results), search_text)
            for url in wiki_results:
                score = _score_url_relevance(url, title, artist)
                all_candidates.append((score, url, False))

    # Source 5: DuckDuckGo (last resort)
    if len(all_candidates) < 2:
        ddg_results = search_duckduckgo(search_text)
        if ddg_results:
            logger.info("Found %d images via DuckDuckGo for '%s'", len(ddg_results), search_text)
            for url in ddg_results:
                all_candidates.append((0, url, False))

    if not all_candidates:
        logger.warning("No images found for '%s'", search_text)
        return [], False

    # Sort by score (highest first), deduplicate
    all_candidates.sort(key=lambda x: x[0], reverse=True)
    seen = set()
    urls = []
    any_verified = False
    for score, url, verified in all_candidates:
        if url not in seen:
            seen.add(url)
            urls.append(url)
            if verified:
                any_verified = True

    return urls, any_verified


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
            headers = dict(BROWSER_HEADERS)
            headers["Referer"] = f"https://{domain}/"

            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                content_type = response.headers.get("Content-Type", "").lower()
                if "image" in content_type:
                    # Determine extension from content type
                    ext = ".jpg"
                    if "png" in content_type:
                        ext = ".png"
                    elif "webp" in content_type:
                        ext = ".webp"

                    filename = f"web_img_{abs(hash(url))}{ext}"
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

def _fetch_single_image(card_id: int, title: str, artist: str) -> tuple[int, str | None, bool]:
    """
    Search + download image for a single card.
    Returns (card_id, filename_or_none, is_verified).
    Always downloads the best image found, whether verified or not.
    """
    try:
        urls, is_verified = search_images(title=title, artist=artist)
        if urls:
            result = download_image(urls)
            if result:
                return card_id, result[0], is_verified
    except Exception as e:
        logger.warning("Image fetch failed for card %d: %s", card_id, e)
    return card_id, None, False


def fetch_images_batch(
    tasks: list[tuple[int, str, str]],
    max_workers: int = 1,
    on_progress: callable = None,
) -> dict[int, tuple[str | None, bool]]:
    """
    Fetch images for multiple cards.

    Args:
        tasks: list of (card_id, title, artist) tuples
        max_workers: number of parallel downloads
        on_progress: callback(card_id, filename, done_count, total)

    Returns:
        dict mapping card_id -> (filename_or_none, is_verified)
        When is_verified=False and filename=None, the painting is likely
        copyrighted and a search link should be used instead.
    """
    results = {}
    total = len(tasks)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_single_image, card_id, title, artist): card_id
            for card_id, title, artist in tasks
        }

        for i, future in enumerate(as_completed(futures), 1):
            card_id, filename, verified = future.result()
            results[card_id] = (filename, verified)
            if on_progress:
                on_progress(card_id, filename, verified, i, total)

    return results
