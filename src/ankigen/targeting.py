"""Decide what to generate today, and render the prompts that will ask for it.

Pure and deterministic: the same collection, profile and `run_date` always
produce the same requests. Rotation through topics and weak cards is seeded by
the date, so consecutive days cover different ground but a rerun of one day
reproduces it exactly. No LLM or embedding calls happen here, which keeps
`ankigen plan` instant.
"""
from __future__ import annotations

import hashlib
import math
import random
import re
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from string import Template

from ankigen.ingest import Note
from ankigen.profile import DeckTarget, Profile

# v2.0 filed cards under a separate top-level inbox. They now go straight into
# the deck (or a subdeck of it), but decks exported by the old layout must still
# count as "already studied" for dedup.
LEGACY_INBOX = "AnkiGen Inbox"
CARDS_PER_TOPIC = 5
AVOID_LIMIT = 40

_STOPWORDS = frozenset(
    "a an and are as at be by does do for from how in is it of on or that the this "
    "to was what when where which who why with you your".split()
)


@dataclass
class GenerationRequest:
    request_id: str
    deck: str
    card_type: str
    n: int
    reason: str  # "topic" | "weak_card" | "gap"
    topic: str | None = None
    focus: str | None = None  # the weak card being re-approached
    style_examples: list[tuple[str, str]] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    prompt: str = ""


# ------------------------------------------------------------ helpers

def in_deck(note_deck: str, target: str) -> bool:
    """A target covers its subdecks, and cards filed by any earlier layout."""
    for root in (target, f"{LEGACY_INBOX}::{target}"):
        if note_deck == root or note_deck.startswith(root + "::"):
            return True
    return False


def _rng(run_date: date, *parts: str) -> random.Random:
    seed = hashlib.sha1("|".join([run_date.isoformat(), *parts]).encode()).hexdigest()
    return random.Random(int(seed[:16], 16))


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_]+", text.lower()) if w not in _STOPWORDS and len(w) > 2}


def _relevance(query: str, text: str) -> float:
    q, t = _tokens(query), _tokens(text)
    return len(q & t) / len(q | t) if q and t else 0.0


def nearest(query: str, notes: list[Note], k: int) -> list[str]:
    """Existing questions most related to what is about to be generated.

    The model can't be shown a 400-card deck without blowing the provider's
    token budget, and the cards it's likeliest to duplicate are the related
    ones, so those are what it sees.
    """
    # Searching the whole collection rather than one deck means a single word
    # in common is no longer evidence of anything: "what makes a backfill
    # cheap or expensive" turned up a card about painters. Ask for two.
    q = _tokens(query)
    need = min(2, len(q))
    scored = [
        (_relevance(query, text), n)
        for n, text in ((n, f"{n.front} {n.back}") for n in notes)
        if len(q & _tokens(text)) >= need
    ]
    # Unrelated cards only spend tokens; the model can't duplicate what it's
    # not writing about.
    ranked = sorted((s for s in scored if s[0] > 0), key=lambda s: (-s[0], s[1].note_id))
    return [n.front for _, n in ranked[:k]]


def is_weak(note: Note, profile: Profile) -> bool:
    rule = profile.weak_cards
    return note.lapses >= rule.min_lapses or (0 < note.ease <= rule.max_ease)


def _style_examples(pool: list[Note], k: int, rng: random.Random) -> list[tuple[str, str]]:
    """Cards the learner has kept around long enough to be representative."""
    candidates = [n for n in pool if n.back and not n.is_cloze and 8 <= len(n.front) <= 250]
    mature = [n for n in candidates if n.interval_days >= 21]
    source = mature if len(mature) >= k else candidates
    picked = rng.sample(source, min(k, len(source)))
    return [(n.front, n.back) for n in sorted(picked, key=lambda n: n.note_id)]


# ------------------------------------------------------------ prompts

def _load(name: str) -> Template:
    return Template(resources.files("ankigen.prompts").joinpath(name).read_text(encoding="utf-8"))


def _bullets(items: list[str], empty: str) -> str:
    return "\n".join(f"- {i}" for i in items) if items else empty


def render_prompt(req: GenerationRequest, profile: Profile, target: DeckTarget) -> str:
    learner, style = profile.learner, profile.style
    wants_images = profile.wants_images(target.deck)

    if req.reason == "weak_card":
        task = (
            f"The learner keeps forgetting this card:\n{req.focus}\n\n"
            f"Write exactly {req.n} new card(s) that teach the same fact from a different "
            "angle: a concrete example, a contrast with a concept it gets confused with, "
            "or the reason it is true. Do not simply rephrase the original."
        )
    elif req.reason == "gap":
        task = (
            f"Write exactly {req.n} new cards on important concepts this deck does not "
            "cover yet. Prefer concepts a practitioner uses often over trivia."
        )
    else:
        task = f'Write exactly {req.n} new cards about: "{req.topic}".'

    rules = [
        "Each card tests ONE specific concept.",
        f"Answers are at most {style.max_answer_words} words.",
        "Be factually precise. If you are not certain a detail is correct, choose a "
        "different concept rather than guess.",
        "Plain text. Use `backticks` for code, identifiers and commands.",
        *style.rules,
    ]

    examples = "\n".join(f"Q: {q}\nA: {a}\n" for q, a in req.style_examples)
    return _load("generate.txt").substitute(
        level=learner.level,
        language=learner.language,
        goals="; ".join(learner.goals) or "not specified",
        deck=req.deck,
        task=task,
        deck_instructions=f"\nDECK-SPECIFIC INSTRUCTIONS\n{target.instructions.strip()}\n"
        if target.instructions.strip() else "",
        examples=examples.strip() or "(no examples available — use a clear, concise style)",
        avoid=_bullets(req.avoid, "(nothing yet — this is a new subject)"),
        rules=_bullets(rules, ""),
        format=_format_contract(req.card_type, wants_images),
    )


def _format_contract(card_type: str, wants_images: bool) -> str:
    """The JSON shape the model must answer with.

    `image_query` goes *inside* the shape rather than being described after it:
    asked for in a trailing paragraph, the model answered with the three keys
    the shape listed and silently dropped the fourth, every time.
    """
    shape = _load(f"format_{card_type}.txt").substitute(
        image_field=', "image_query": "..."' if wants_images else ""
    ).strip()
    return shape + (_load("image_hint.txt").template.rstrip() if wants_images else "")


# ------------------------------------------------------------ targeting

def build_requests(profile: Profile, notes: list[Note], run_date: date) -> list[GenerationRequest]:
    requests: list[GenerationRequest] = []
    budget = profile.global_quota
    all_targeted = [n for n in notes if any(in_deck(n.deck, t.deck) for t in profile.decks)]

    for target in profile.decks:
        quota = min(target.daily_quota, budget)
        if quota <= 0:
            continue
        rng = _rng(run_date, target.deck)
        deck_notes = [n for n in notes if in_deck(n.deck, target.deck)]
        # A brand-new subject has no cards of its own to imitate; borrow the
        # learner's voice from the rest of what they study.
        style_pool = deck_notes or all_targeted
        k = profile.style.examples_per_prompt
        deck_reqs: list[GenerationRequest] = []

        def add(reason: str, n: int, topic: str | None = None, focus: Note | None = None):
            query = focus.front if focus else (topic or target.deck)
            deck_reqs.append(GenerationRequest(
                request_id=hashlib.sha1(
                    f"{run_date}|{target.deck}|{reason}|{topic}|{focus.note_id if focus else ''}".encode()
                ).hexdigest()[:12],
                deck=target.deck,
                card_type=target.card_type,
                n=n,
                reason=reason,
                topic=topic,
                focus=f"Q: {focus.front}\nA: {focus.back}" if focus else None,
                style_examples=_style_examples(style_pool, k, rng),
                # Drawn from the whole collection, not just this deck: dedup
                # would drop a card that repeats something filed elsewhere, so
                # asking for it at all wastes a request, and free tiers ration
                # those by the day.
                avoid=nearest(query, notes, AVOID_LIMIT),
            ))

        # 1. Weak cards first: fixing what the learner keeps failing beats new material.
        if profile.weak_cards.enabled and target.card_type != "cloze":
            weak = sorted(
                (n for n in deck_notes if is_weak(n, profile) and n.back),
                key=lambda n: (-n.lapses, n.ease or 9999, n.note_id),
            )
            # Rotate through the weakest dozen so it isn't the same card daily.
            pool = weak[:12]
            rng.shuffle(pool)
            for note in pool[: min(profile.weak_cards.max_per_deck, quota)]:
                add("weak_card", 1, focus=note)
            quota -= len(deck_reqs)

        # 2. Topics, rotated by date; a few cards each so a topic gets depth.
        if quota > 0 and target.topics:
            n_topics = min(len(target.topics), math.ceil(quota / CARDS_PER_TOPIC))
            start = run_date.toordinal() % len(target.topics)
            chosen = [target.topics[(start + i) % len(target.topics)] for i in range(n_topics)]
            share, extra = divmod(quota, n_topics)
            for i, topic in enumerate(chosen):
                if share + (i < extra):
                    add("topic", share + (i < extra), topic=topic)
        # 3. No topics given: let the model find what the deck is missing.
        elif quota > 0:
            add("gap", quota, topic=target.deck.split("::")[-1])

        for req in deck_reqs:
            req.prompt = render_prompt(req, profile, target)
        budget -= sum(r.n for r in deck_reqs)
        requests.extend(deck_reqs)
        if budget <= 0:
            break

    return requests


REQUEST_COLUMNS = ("run_date", "request_id", "deck", "topic", "card_type", "n", "reason", "focus", "prompt")


def save_requests(wh, run_date: date, requests: list[GenerationRequest]) -> int:
    return wh.replace_partition("requests", run_date, REQUEST_COLUMNS, [
        (run_date, r.request_id, r.deck, r.topic, r.card_type, r.n, r.reason, r.focus, r.prompt)
        for r in requests
    ])


def load_requests(wh, run_date: date) -> list[dict]:
    return wh.query(
        "SELECT * FROM requests WHERE run_date = ? ORDER BY deck, request_id", [run_date]
    )
