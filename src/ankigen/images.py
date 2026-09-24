"""Find and store an illustration for a card.

Images come from web search (DuckDuckGo, which falls back to other engines on
its own). Wikimedia Commons used to sit behind it as a second source, and was
removed: its full-text search matches file *descriptions*, so it answers every
query with something, and for software topics that something was reliably a
stock photograph. A card with no picture beats a card with the wrong one.

Search engines match the words around a picture and never the picture itself,
so what comes back is checked by a model before it is used — see `fetch`. A
picture that could not be checked is not used: on a day the search engine
served a runner Paw Patrol costumes for "S3 storage classes", the four
pictures that went out unchecked were the four that should not have.

Everything is saved as JPEG. Anki imports JPEG reliably; PNG and WebP caused
import problems in v1, so conversion is unconditional rather than best-effort.
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image

logger = logging.getLogger(__name__)

MAX_WIDTH = 800
MIN_SOURCE_WIDTH = 300
TIMEOUT = 15
# About half a minute of patience per query, spread over four tries. A result
# page with nothing relevant on it counts as a failed try, so this is also how
# long a query waits out a search engine that is serving junk.
DDG_ATTEMPTS = 4
# How many candidate pictures to look at before giving up on a card. Each look
# is one request on a metered free tier, and a run once spent forty of them —
# most of the checker's day — rejecting junk. Candidates are filtered by their
# titles first now, so the ones that reach the checker are worth looking at.
MAX_CHECKS = 3
# Looks per run, across every card: the checker's allowance also has to cover
# fact-checking the cards themselves, and any manual runs later in the day.
RUN_CHECK_BUDGET = 24
UNCHECKED = "unchecked"
DDG_BACKOFF_CAP = 60
USER_AGENT = "AnkiGen/2.1 (personal flashcard generator)"


@dataclass
class ImageResult:
    card_uid: str
    query: str
    filename: str | None = None
    source: str | None = None       # "duckduckgo" | "cached"
    url: str = ""                   # where the picture came from, for provenance
    detail: str = ""                # why it failed, when it did

    @property
    def found(self) -> bool:
        return self.filename is not None


# ----------------------------------------------------------------- search

def with_context(query: str, context: str) -> str:
    """The query with the deck's subject in front, said once.

    Words of the context already in the query are taken out rather than
    skipped, so "airflow pool slots diagram" becomes "Apache Airflow pool
    slots diagram" and not "Apache Airflow airflow pool slots diagram".
    """
    context = (context or "").strip()
    if not context or not (query or "").strip():
        return query
    have = {w.lower() for w in context.split()}
    rest = [w for w in query.split() if w.lower() not in have]
    return " ".join([context, *rest])


def _width(value) -> int:
    """`ddgs` falls back to other engines when DuckDuckGo itself fails, and they
    do not agree on the type of `width`: Bing reports it as a string, which once
    made the comparison below raise and threw away every result."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# Words that say what kind of picture is wanted rather than what it is of.
# A result that matches only these matched nothing.
_GENERIC = frozenset("""
    diagram diagrams table tables chart charts comparison compare compared vs versus
    architecture overview explained explanation illustration illustrated timeline flow
    flowchart relationship relationships example examples picture image images visual
    lifecycle life cycle how what why when which the a an of and or in on for to with
    between into from by is are its using use used
""".split())


def topic_terms(query: str, context: str = "") -> set[str]:
    """The words of a query that name its subject.

    The deck's context ("Apache Airflow") is left out on purpose: it is
    there to steer the search engine, and a result that matches only it
    matched the wrong thing — the attack helicopter matched "Apache".
    """
    ignore = _GENERIC | {w.lower() for w in re.findall(r"[A-Za-z0-9]+", context)}
    return {w for w in re.findall(r"[a-z0-9]+", query.lower())
            if w not in ignore and len(w) > 2}


def looks_relevant(terms: set[str], *texts: str) -> bool:
    """Does a result's title or address mention the subject at all?

    Free to ask, unlike the checker: on bad days the search engine answers a
    runner with trending pictures — costume photos, a TV poster — under titles
    that share no word with the query, and each of those used to cost a look.
    Endings are trimmed so "pools" finds "pool" and "classes" finds "class".
    """
    if not terms:
        return True
    haystack = " ".join(t.lower() for t in texts if t)
    return any(t[:max(4, len(t) - 2)] in haystack for t in terms)


def search_duckduckgo(query: str, limit: int = 10, attempts: int = DDG_ATTEMPTS,
                      context: str = "") -> list[tuple[str, str]]:
    """(image url, page url) for a query, best sources first, retried patiently.

    This is by far the better source, so it is worth waiting for: a run is a
    daily batch with nobody watching, and a minute of backoff costs nothing
    against coming back with no picture. Every failure is retried, not only
    rate limits — the search fails in several ways (the engine erroring,
    falling back to another engine, or simply answering with nothing) and none
    of them mean the next attempt will fail too.
    """
    from ddgs import DDGS

    terms = topic_terms(query, context)
    for attempt in range(attempts):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.images(query, max_results=limit))
            usable = [
                r for r in results
                if r.get("image") and _width(r.get("width")) >= MIN_SOURCE_WIDTH
                and not _looks_like_junk(r.get("image"))
                and not _looks_like_junk(r.get("url"))
            ]
            relevant = [r for r in usable
                        if looks_relevant(terms, r.get("title", ""), r.get("url", ""), r["image"])]
            urls = [(r["image"], r.get("url") or "") for r in relevant]
            # Stable within each group, so search relevance still decides
            # between two equally reputable sources.
            urls.sort(key=_rank)
            if urls:
                return urls
            reason = (f"nothing about {' / '.join(sorted(terms))} in {len(usable)} results"
                      if usable else "no results")
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
    # More of the same SEO farms, on another cloud's storage.
    "blob.core.windows.net",
    # Refuses every download with 403, so a result from it is a wasted slot.
    "researchgate.net",
)


def _looks_like_junk(url: str) -> bool:
    u = (url or "").lower()
    return any(host in u for host in _JUNK_HOSTS)


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


# Where a technical diagram is likely to come from. Search relevance alone put
# a duck ahead of airflow.apache.org for "airflow deferrable operator
# triggerer architecture", and taking the first result that downloaded is how
# it ended up on a card. Ranking by source before spending a check on it means
# the official documentation gets looked at first.
_PREFERRED_HOSTS = (
    "apache.org", "kubernetes.io", "docker.com", "aws.amazon.com", "cloud.google.com",
    "learn.microsoft.com", "postgresql.org", "wikipedia.org", "wikimedia.org",
    "github.io", "readthedocs.io", "stackexchange.com", "stackoverflow.com",
    "medium.com", "towardsdatascience.com", "dev.to", "zenn.dev",
    "databricks.com", "snowflake.com", "confluent.io", "getdbt.com", "dbt.com",
    "grafana.com", "oras.land", "bytebytego.com",
)


def _preferred(host: str) -> bool:
    """By host, not by substring: matching ".edu" anywhere in the address put
    an SEO farm at udlvirtual.edu.pe ahead of the Airflow documentation."""
    return host.endswith(".edu") or any(
        host == h or host.endswith("." + h) for h in _PREFERRED_HOSTS)


def _rank(candidate: tuple[str, str]) -> int:
    """0 for a source worth trying first, 1 for anything else."""
    return 0 if _preferred(_host(candidate[1])) else 1


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


class CheckBudget:
    """Looks left for this run, shared by the workers fetching in parallel."""

    def __init__(self, looks: int):
        self._left = looks
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            if self._left <= 0:
                return False
            self._left -= 1
            return True

    def exhaust(self) -> None:
        with self._lock:
            self._left = 0


# A picture carried inside a note is paid for in the size of your collection,
# which syncs whole to every device, so inline copies are smaller than the
# files the .apkg export carries.
INLINE_WIDTH = 640
INLINE_QUALITY = 72


def inline_src(path: Path) -> str:
    """The picture as a `data:` URI, small enough to live inside a note."""
    with Image.open(path) as img:
        img = img.convert("RGB")
        if img.width > INLINE_WIDTH:
            img = img.resize((INLINE_WIDTH, int(img.height * INLINE_WIDTH / img.width)),
                             Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=INLINE_QUALITY, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def fetch(card_uid: str, query: str, media_dir: Path, card: str = "",
          verifier=None, max_checks: int = MAX_CHECKS, context: str = "",
          budget: CheckBudget | None = None) -> ImageResult:
    """First *usable* image for a query.

    With a `verifier`, usable means something looked at the picture and said it
    illustrates the card. Nothing short of that works: search results come from
    pages whose text matched the query, and the picture on such a page is
    frequently unrelated to it. When nothing can look — the checker is down or
    its allowance is spent — the card goes without a picture.
    """
    if not query or len(query.strip()) < 3:
        return ImageResult(card_uid, query, detail="no image query")

    source = "duckduckgo"
    checks = 0
    for url, page in search_duckduckgo(query, context=context):
        name = download_as_jpeg(url, query, media_dir)
        if not name:
            continue
        if not (verifier and card):
            return ImageResult(card_uid, query, filename=name, source=source, url=page)
        if checks >= max_checks or (budget and not budget.take()):
            # Every look costs a request on a metered free tier, so stop rather
            # than work through the whole result page.
            (media_dir / name).unlink(missing_ok=True)
            why = (f"no relevant image in the first {checks} checked" if checks >= max_checks
                   else "the run's budget for checking images is spent")
            return ImageResult(card_uid, query, detail=why)
        try:
            keep, shows = verifier((media_dir / name).read_bytes(), card, query)
        except Exception as e:
            logger.info("Cannot check images (%s); leaving the card without one", e)
            (media_dir / name).unlink(missing_ok=True)
            if budget and "quota" in str(e).lower():
                budget.exhaust()            # nothing will be able to look today
            return ImageResult(card_uid, query, detail=f"{UNCHECKED}: {e}")
        checks += 1
        if keep:
            return ImageResult(card_uid, query, filename=name, source=source, url=page,
                               detail=f"shows {shows}")
        logger.info("Rejected an image for %r: it shows %s", query, shows)
        (media_dir / name).unlink(missing_ok=True)

    logger.info("No usable image for %r", query)
    return ImageResult(card_uid, query, detail="no usable image found")


def fetch_many(jobs: list[tuple], media_dir: Path, workers: int = 3,
               verifier=None, check_budget: int = RUN_CHECK_BUDGET) -> list[ImageResult]:
    """Fetch concurrently, but gently — DuckDuckGo throttles parallel callers."""
    if not jobs:
        return []
    budget = CheckBudget(check_budget)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # A job is (card_uid, query), optionally followed by the card's text
        # and the deck's search context.
        jobs = [(j[0], j[1], j[2] if len(j) > 2 else "", j[3] if len(j) > 3 else "")
                for j in jobs]
        futures = [pool.submit(fetch, uid, query, media_dir, card, verifier,
                               context=context, budget=budget)
                   for uid, query, card, context in jobs]
        results = []
        for (uid, query, _card, _context), future in zip(jobs, futures):
            try:
                results.append(future.result())
            except Exception as e:                      # never let one image kill the stage
                results.append(ImageResult(uid, query, detail=str(e)))
    return results
