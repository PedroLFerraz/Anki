"""The prompt profile: who the learner is and what each run should produce."""
from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

CardType = Literal["basic", "cloze", "detailed"]
# A topic gets a few cards, so it is covered in some depth rather than once.
CARDS_PER_TOPIC = 5


class Learner(BaseModel):
    level: str = "intermediate"
    language: str = "English"
    goals: list[str] = Field(default_factory=list)


class Style(BaseModel):
    rules: list[str] = Field(default_factory=list)
    max_answer_words: int = 40
    # Few-shot examples drawn from the learner's own cards, per prompt.
    examples_per_prompt: int = Field(default=4, ge=0, le=10)


class WeakCards(BaseModel):
    """Cards the learner keeps failing get a fresh angle instead of a rephrase."""

    enabled: bool = True
    min_lapses: int = 2
    # Anki stores ease as permille: 2500 is the default, 1300 the floor.
    max_ease: int = 2100
    max_per_deck: int = 2


class DeckTarget(BaseModel):
    deck: str
    # Fetch an illustration when the model judges one genuinely helps.
    images: bool | None = None
    # Put in front of every image search for this deck, e.g. "Apache Airflow".
    # The model writing the query knows the deck and still shortens the name,
    # and a search engine reads "airflow pool" as a swimming pool.
    image_context: str = ""
    daily_quota: int = Field(default=5, ge=0)
    card_type: CardType = "basic"
    topics: list[str] = Field(default_factory=list)
    instructions: str = ""
    # A subject the collection doesn't have yet — nothing to learn style from.
    new_deck: bool = False
    # A curriculum deck: nothing before this date, then its topics once, in
    # order from the first, then nothing. Without it, topics rotate forever.
    start: date | None = None

    @field_validator("deck")
    @classmethod
    def _normalise(cls, v: str) -> str:
        return "::".join(part.strip() for part in v.split("::"))

    @property
    def topics_per_day(self) -> int:
        return max(1, math.ceil(self.daily_quota / CARDS_PER_TOPIC))

    @property
    def last_day(self) -> date | None:
        """The day a phased deck writes its last topic."""
        if self.start is None or not self.topics or self.daily_quota <= 0:
            return None
        days = math.ceil(len(self.topics) / self.topics_per_day)
        return self.start + timedelta(days=days - 1)

    def topics_on(self, run_date: date) -> list[str]:
        """A phased deck's topics for one day; empty outside its window."""
        day = (run_date - self.start).days if self.start else -1
        if day < 0:
            return []
        first = day * self.topics_per_day
        return self.topics[first:first + self.topics_per_day]


class Profile(BaseModel):
    learner: Learner = Field(default_factory=Learner)
    style: Style = Field(default_factory=Style)
    weak_cards: WeakCards = Field(default_factory=WeakCards)
    decks: list[DeckTarget]
    global_quota: int = Field(default=20, ge=1)
    verify: bool = True
    images: bool = True
    # Show each candidate picture to the model before attaching it. Search
    # engines match the words on a page, not the picture on it, so this is the
    # only check that catches a relevant-looking result with a stock photo on it.
    verify_images: bool = True

    # Where generated notes land inside the target deck. Empty (the default)
    # means straight into the deck itself, tagged `ankigen::run_<date>`, so
    # nothing has to be moved afterwards. Set e.g. "AnkiGen" to park them in a
    # subdeck such as `DS::SQL::AnkiGen` instead.
    inbox: str = ""

    def wants_images(self, deck: str) -> bool:
        for target in self.decks:
            if target.deck == deck:
                return self.images if target.images is None else target.images
        return self.images

    def image_context_for(self, deck: str) -> str:
        for target in self.decks:
            if target.deck == deck:
                return target.image_context
        return ""

    def deck_for(self, deck: str) -> str:
        """The Anki deck a generated card is filed under."""
        return f"{deck}::{self.inbox}" if self.inbox else deck

    def validate_against(self, existing_decks: set[str]) -> list[str]:
        """Problems that would make a run silently produce nothing."""
        problems = []
        for target in self.decks:
            exists = any(
                d == target.deck or d.startswith(target.deck + "::") for d in existing_decks
            )
            if not exists and not target.new_deck:
                problems.append(
                    f"Deck {target.deck!r} is not in the collection. "
                    "Fix the name, or set `new_deck: true` to start a new subject."
                )
            if target.new_deck and not target.topics:
                problems.append(
                    f"New deck {target.deck!r} needs `topics:` — there are no existing "
                    "cards to infer a subject from."
                )
        return problems + self.schedule_problems()

    def phased(self) -> list[DeckTarget]:
        """Decks with a start date, in the order they begin."""
        return sorted((t for t in self.decks if t.last_day), key=lambda t: t.start)

    def schedule_problems(self) -> list[str]:
        """Days when the running decks want more cards than the daily total.

        The planner walks the decks in profile order and stops when the budget
        is spent, so a deck past the total gets nothing, and says nothing.
        """
        phased = self.phased()
        if not phased:
            return []
        always = sum(t.daily_quota for t in self.decks if t.start is None)
        problems, seen = [], set()
        day, end = phased[0].start, max(t.last_day for t in phased)
        while day <= end:
            running = [t for t in phased if t.start <= day <= t.last_day]
            names = tuple(t.deck for t in running)
            if always + sum(t.daily_quota for t in running) > self.global_quota and names not in seen:
                seen.add(names)
                problems.append(
                    f"From {day}, {' and '.join(names)} run together and want more than "
                    f"global_quota ({self.global_quota}) cards a day. Move a `start:` or "
                    "lower a `daily_quota`."
                )
            day += timedelta(days=1)
        return problems

    def next_free_day(self) -> date | None:
        """The day after the last phased deck finishes, if any are phased."""
        phased = self.phased()
        return max(t.last_day for t in phased) + timedelta(days=1) if phased else None


def load_profile(path: str | Path) -> Profile:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Profile.model_validate(data)
