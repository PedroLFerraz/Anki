"""
Query Wikidata SPARQL endpoint for artworks by artist or topic.

Replaces LLM-based card generation for artwork decks with verified
structured data from Wikidata. Supports queries by:
- Artist name (e.g. "Claude Monet")
- Art movement (e.g. "Impressionism")
- Museum/location (e.g. "Louvre")
- Time period (e.g. "1800s", "19th century")
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {"Accept": "application/json", "User-Agent": "AnkiArtworkBot/1.0"}

# Wikidata artwork types (P31 values)
ARTWORK_TYPES = (
    "wd:Q3305213",   # painting
    "wd:Q93184",     # drawing
    "wd:Q18573970",  # mural
    "wd:Q15123870",  # artwork
    "wd:Q860861",    # sculpture
    "wd:Q4502142",   # visual artwork
    "wd:Q11060274",  # print
    "wd:Q17514",     # watercolor painting
)

SPARQL_TEMPLATE = """
SELECT DISTINCT ?artwork ?artworkLabel ?image ?date
       ?medium ?mediumLabel ?location ?locationLabel
       ?movement ?movementLabel ?nationality ?nationalityLabel
WHERE {{
  ?artist rdfs:label "{artist_name}"@{lang} .
  ?artwork wdt:P170 ?artist .
  ?artwork wdt:P31 ?type .
  VALUES ?type {{ {artwork_types} }}
  OPTIONAL {{ ?artwork wdt:P18 ?image . }}
  OPTIONAL {{ ?artwork wdt:P571 ?date . }}
  OPTIONAL {{ ?artwork wdt:P186 ?medium . }}
  OPTIONAL {{ ?artwork wdt:P276 ?location . }}
  OPTIONAL {{ ?artwork wdt:P135 ?movement . }}
  OPTIONAL {{ ?artist wdt:P27 ?nationality . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{lang},en,pt,es,fr" . }}
}}
ORDER BY ?date
"""

# Fallback: search by text match instead of exact label
SPARQL_SEARCH_TEMPLATE = """
SELECT DISTINCT ?artwork ?artworkLabel ?image ?date
       ?medium ?mediumLabel ?location ?locationLabel
       ?movement ?movementLabel ?nationality ?nationalityLabel
WHERE {{
  SERVICE wikibase:mwapi {{
    bd:serviceParam wikibase:endpoint "www.wikidata.org" ;
                    wikibase:api "EntitySearch" ;
                    mwapi:search "{artist_name}" ;
                    mwapi:language "en" .
    ?artist wikibase:apiOutputItem mwapi:item .
  }}
  ?artist wdt:P31 wd:Q5 .
  ?artwork wdt:P170 ?artist .
  ?artwork wdt:P31 ?type .
  VALUES ?type {{ {artwork_types} }}
  OPTIONAL {{ ?artwork wdt:P18 ?image . }}
  OPTIONAL {{ ?artwork wdt:P571 ?date . }}
  OPTIONAL {{ ?artwork wdt:P186 ?medium . }}
  OPTIONAL {{ ?artwork wdt:P276 ?location . }}
  OPTIONAL {{ ?artwork wdt:P135 ?movement . }}
  OPTIONAL {{ ?artist wdt:P27 ?nationality . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,pt,es,fr" . }}
}}
ORDER BY ?date
"""


# --- Topic-based SPARQL templates ---

# Query artworks by entity ID (movement, location, or genre)
# Simplified: only paintings (Q3305213), fewer OPTIONALs for query performance
SPARQL_BY_ENTITY = """
SELECT DISTINCT ?artwork ?artworkLabel ?image ?date
       ?locationLabel ?movementLabel
       ?artist ?artistLabel
WHERE {{
  ?artwork wdt:{property} wd:{entity_id} .
  ?artwork wdt:P31 wd:Q3305213 .
  ?artwork wdt:P170 ?artist .
  OPTIONAL {{ ?artwork wdt:P18 ?image . }}
  OPTIONAL {{ ?artwork wdt:P571 ?date . }}
  OPTIONAL {{ ?artwork wdt:P276 ?location . }}
  OPTIONAL {{ ?artwork wdt:P135 ?movement . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,pt,es,fr" . }}
}}
LIMIT {limit}
"""

# Period query: require image to keep results manageable and useful
SPARQL_BY_PERIOD = """
SELECT DISTINCT ?artwork ?artworkLabel ?image ?date
       ?locationLabel ?movementLabel
       ?artist ?artistLabel
WHERE {{
  ?artwork wdt:P31 wd:Q3305213 .
  ?artwork wdt:P170 ?artist .
  ?artwork wdt:P571 ?date .
  ?artwork wdt:P18 ?image .
  FILTER(YEAR(?date) >= {year_start} && YEAR(?date) < {year_end})
  OPTIONAL {{ ?artwork wdt:P276 ?location . }}
  OPTIONAL {{ ?artwork wdt:P135 ?movement . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,pt,es,fr" . }}
}}
LIMIT {limit}
"""

# Properties that link artworks to topics
# P135 = movement, P276 = location, P136 = genre, P195 = collection
TOPIC_PROPERTIES = ["P135", "P276", "P136", "P195"]


def _parse_date_range(topic: str) -> Optional[tuple]:
    """Parse a date range from topic string. Returns (year_start, year_end) or None."""
    # "1800s" → 1800-1900
    m = re.match(r"^(\d{4})s$", topic.strip())
    if m:
        start = int(m.group(1))
        return (start, start + 100)

    # "19th century" → 1800-1900
    m = re.match(r"^(\d{1,2})(st|nd|rd|th)\s+century$", topic.strip(), re.IGNORECASE)
    if m:
        century = int(m.group(1))
        return ((century - 1) * 100, century * 100)

    # "1500-1600" → 1500-1600
    m = re.match(r"^(\d{4})\s*[-–]\s*(\d{4})$", topic.strip())
    if m:
        return (int(m.group(1)), int(m.group(2)))

    return None


def _search_entity(topic: str) -> List[dict]:
    """Search Wikidata for entities matching the topic string.
    Returns list of {id, label, description} dicts."""
    try:
        resp = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": topic,
                "language": "en",
                "format": "json",
                "limit": 5,
            },
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("search", [])
    except Exception as e:
        logger.debug("Entity search failed for '%s': %s", topic, e)
    return []


def query_artworks_by_topic(topic: str, limit: int = 30) -> List[dict]:
    """
    Query Wikidata for artworks matching a topic.

    Tries in order:
    1. Date range: "1800s", "19th century", "1500-1600"
    2. Entity search → query by movement/location/genre/collection
    """
    # 1. Try as date range (no entity search needed)
    date_range = _parse_date_range(topic)
    if date_range:
        query = SPARQL_BY_PERIOD.format(
            year_start=date_range[0],
            year_end=date_range[1],
            limit=limit,
        )
        results = _execute_sparql(query, timeout=90)
        if results:
            logger.info("Found %d artworks for period '%s'", len(results), topic)
            return results

    # 2. Search for the topic entity, then query artworks linked to it
    entities = _search_entity(topic)
    if not entities:
        logger.warning("No Wikidata entities found for '%s'", topic)
        return []

    # Try each entity with each property (movement, location, genre, collection)
    for entity in entities:
        entity_id = entity["id"]
        for prop in TOPIC_PROPERTIES:
            query = SPARQL_BY_ENTITY.format(
                property=prop,
                entity_id=entity_id,
                limit=limit,
            )
            results = _execute_sparql(query)
            if results:
                logger.info(
                    "Found %d artworks for '%s' (entity %s, property %s)",
                    len(results), topic, entity_id, prop,
                )
                return results

    logger.warning("No artworks found for topic '%s' on Wikidata", topic)
    return []


def query_artist_artworks(artist_name: str) -> List[dict]:
    """
    Query Wikidata for all artworks by the given artist.

    Returns list of dicts with keys: title, image_url, date, medium,
    location, movement, nationality, wikidata_id.

    Results are sorted for variety: unique titles first, then duplicates.
    """
    results = None
    # Try exact label match in multiple languages
    for lang in ("en", "pt", "es", "fr", "it", "de"):
        results = _try_sparql_query(artist_name, lang)
        if results:
            logger.info("Found %d artworks for '%s' via %s label", len(results), artist_name, lang)
            break

    # Fallback: text search
    if not results:
        results = _try_sparql_search(artist_name)
        if results:
            logger.info("Found %d artworks for '%s' via text search", len(results), artist_name)

    if not results:
        logger.warning("No artworks found for '%s' on Wikidata", artist_name)
        return []

    return _sort_for_variety(results)


def _try_sparql_query(artist_name: str, lang: str) -> List[dict]:
    """Try SPARQL query with exact artist label in a specific language."""
    # Escape quotes in artist name for SPARQL
    safe_name = artist_name.replace('"', '\\"')
    query = SPARQL_TEMPLATE.format(
        artist_name=safe_name,
        lang=lang,
        artwork_types=" ".join(ARTWORK_TYPES),
    )
    return _execute_sparql(query)


def _try_sparql_search(artist_name: str) -> List[dict]:
    """Fallback: use Wikidata entity search API to find the artist."""
    safe_name = artist_name.replace('"', '\\"')
    query = SPARQL_SEARCH_TEMPLATE.format(
        artist_name=safe_name,
        artwork_types=" ".join(ARTWORK_TYPES),
    )
    return _execute_sparql(query)


def _execute_sparql(query: str, timeout: int = 30) -> List[dict]:
    """Execute a SPARQL query and parse results."""
    try:
        resp = requests.get(
            SPARQL_ENDPOINT,
            params={"query": query},
            headers=HEADERS,
            timeout=timeout,
        )
        if resp.status_code != 200:
            logger.debug("SPARQL query failed with status %d", resp.status_code)
            return []
        data = resp.json()
        return _parse_sparql_results(data)
    except Exception as e:
        logger.debug("SPARQL query error: %s", e)
        return []


def _parse_sparql_results(data: dict) -> List[dict]:
    """Parse SPARQL JSON results into card-compatible dicts."""
    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        return []

    # Deduplicate by artwork URI (multiple mediums/movements produce duplicate rows)
    seen = {}
    for row in bindings:
        artwork_uri = row.get("artwork", {}).get("value", "")
        wikidata_id = artwork_uri.split("/")[-1] if artwork_uri else ""

        if wikidata_id in seen:
            # Merge additional medium/movement values
            existing = seen[wikidata_id]
            _merge_field(existing, "medium", _get_val(row, "mediumLabel"))
            _merge_field(existing, "movement", _get_val(row, "movementLabel"))
            _merge_field(existing, "nationality", _get_val(row, "nationalityLabel"))
            continue

        title = _get_val(row, "artworkLabel") or ""
        # Skip if title is just the Q-number (unresolved label)
        if re.match(r"^Q\d+$", title):
            continue

        date_raw = _get_val(row, "date") or ""
        date = _extract_year(date_raw)

        seen[wikidata_id] = {
            "title": title,
            "image_url": _get_val(row, "image"),
            "date": date,
            "medium": _get_val(row, "mediumLabel") or "",
            "location": _get_val(row, "locationLabel") or "",
            "movement": _get_val(row, "movementLabel") or "",
            "nationality": _get_val(row, "nationalityLabel") or "",
            "artist": _get_val(row, "artistLabel") or "",
            "wikidata_id": wikidata_id,
        }

    return list(seen.values())


def _get_val(row: dict, key: str) -> Optional[str]:
    """Extract value from a SPARQL binding row."""
    entry = row.get(key)
    if entry:
        return entry.get("value")
    return None


def _merge_field(record: dict, field: str, new_value: Optional[str]):
    """Add a new value to a field if not already present."""
    if not new_value:
        return
    existing = record.get(field, "")
    if new_value not in existing:
        if existing:
            record[field] = f"{existing}, {new_value}"
        else:
            record[field] = new_value


def base_title(title: str) -> str:
    """Normalize a title for dedup/grouping: remove dates, parentheticals, collapse whitespace."""
    t = title.lower().strip()
    t = re.sub(r"\s*\(.*?\)\s*$", "", t)
    t = re.sub(r"\s*\d{4}\s*$", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _sort_for_variety(artworks: List[dict]) -> List[dict]:
    """Sort artworks so unique titles come first, similar titles later.

    Monet has 183 "Water Lilies" variants — we want to show diverse works
    first and group similar-titled ones at the end.
    """
    # Normalize title to a base form for grouping
    def _base_title(title: str) -> str:
        t = title.lower().strip()
        # Remove parenthetical suffixes like "(study)" or "(detail)"
        t = re.sub(r"\s*\(.*?\)\s*$", "", t)
        # Remove trailing numbers/years
        t = re.sub(r"\s*\d{4}\s*$", "", t)
        # Collapse whitespace
        t = re.sub(r"\s+", " ", t).strip()
        return t

    # Group by base title
    groups = {}
    for art in artworks:
        base = _base_title(art["title"])
        if base not in groups:
            groups[base] = []
        groups[base].append(art)

    # Build result: take one from each group first (round-robin), then seconds, etc.
    # Within each group, prefer artworks with images
    for group in groups.values():
        group.sort(key=lambda a: (not a.get("image_url"), a.get("date", "")))

    result = []
    round_num = 0
    while True:
        added = False
        for group in groups.values():
            if round_num < len(group):
                result.append(group[round_num])
                added = True
        if not added:
            break
        round_num += 1

    return result


def _extract_year(date_str: str) -> str:
    """Extract year from ISO date string like '1886-01-01T00:00:00Z'."""
    if not date_str:
        return ""
    match = re.match(r"(\d{4})", date_str)
    return match.group(1) if match else date_str


def artworks_to_card_fields(artworks: List[dict], artist_name: str = "") -> List[dict]:
    """
    Convert Wikidata artwork dicts to Anki card field dicts
    matching the artwork deck schema.

    If artist_name is empty, uses the 'artist' field from each artwork dict
    (populated by topic-based queries).
    """
    cards = []
    for art in artworks:
        fields = {
            "Artwork": "",  # Will be filled when image is downloaded
            "Artist": artist_name or art.get("artist", ""),
            "Title": art["title"],
            "Subtitle/Alternate Titles": "",
            "Title in Original Language": "",
            "Date": art["date"],
            "Period/Movement": art["movement"],
            "Medium": art["medium"],
            "Nationality": art["nationality"],
            "Note": "",
            "Image Source": art.get("image_url") or "",
            "Image copyright information": "",
            "Permanent Location": art["location"],
            "Instructive Link(s)": "",
            "Gallery/Museum Link(s)": "",
        }
        cards.append(fields)
    return cards
