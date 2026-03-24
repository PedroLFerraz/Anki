"""
Query Wikidata SPARQL endpoint for artworks by a given artist.

Replaces LLM-based card generation for artwork decks with verified
structured data from Wikidata.
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


def query_artist_artworks(artist_name: str) -> List[dict]:
    """
    Query Wikidata for all artworks by the given artist.

    Returns list of dicts with keys: title, image_url, date, medium,
    location, movement, nationality, wikidata_id.
    """
    # Try exact label match in multiple languages
    for lang in ("en", "pt", "es", "fr", "it", "de"):
        results = _try_sparql_query(artist_name, lang)
        if results:
            logger.info("Found %d artworks for '%s' via %s label", len(results), artist_name, lang)
            return results

    # Fallback: text search
    results = _try_sparql_search(artist_name)
    if results:
        logger.info("Found %d artworks for '%s' via text search", len(results), artist_name)
        return results

    logger.warning("No artworks found for '%s' on Wikidata", artist_name)
    return []


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


def _execute_sparql(query: str) -> List[dict]:
    """Execute a SPARQL query and parse results."""
    try:
        resp = requests.get(
            SPARQL_ENDPOINT,
            params={"query": query},
            headers=HEADERS,
            timeout=15,
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


def _extract_year(date_str: str) -> str:
    """Extract year from ISO date string like '1886-01-01T00:00:00Z'."""
    if not date_str:
        return ""
    match = re.match(r"(\d{4})", date_str)
    return match.group(1) if match else date_str


def artworks_to_card_fields(artworks: List[dict], artist_name: str) -> List[dict]:
    """
    Convert Wikidata artwork dicts to Anki card field dicts
    matching the artwork deck schema.
    """
    cards = []
    for art in artworks:
        fields = {
            "Artwork": "",  # Will be filled when image is downloaded
            "Artist": artist_name,
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
