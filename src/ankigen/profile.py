"""The prompt profile: who the learner is and what each run should produce."""
from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator

CardType = Literal["basic", "cloze", "detailed"]
# What a topic's cards look like, which decides their shape and size (see the
# kind_*.txt prompts): a task and the command for it, a shortcut, a one-line
# idea, a real file with parts hidden, or a situation and why it happens.
Kind = Literal["command", "shortcut", "concept", "build", "scenario"]
KINDS = ("command", "shortcut", "concept", "build", "scenario")
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
    # Cards on the start day, when that day should be a kickoff: 100 lays the
    # first twenty topics down at once, then daily_quota carries on. Allowed
    # past global_quota on that one day.
    first_day_quota: int | None = Field(default=None, ge=1)
    # The curriculum by level, 1 (never used it) to 4 (interview), each a list
    # of `- kind: topic`. Flattened in order into `topics`, so dates and the
    # daily plan work exactly as for a plain list.
    levels: dict[int, list[dict[Kind, str]]] | None = None
    _plan: dict[str, tuple[str, int]] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _flatten_levels(self) -> "DeckTarget":
        if not self.levels:
            return self
        given, self.topics = self.topics, []
        for level in sorted(self.levels):
            if not 1 <= level <= 4:
                raise ValueError(f"{self.deck}: levels run from 1 to 4, not {level}.")
            for entry in self.levels[level]:
                if len(entry) != 1:
                    raise ValueError(f"{self.deck}: write each topic as `- kind: topic`, "
                                     f"one per line; got {entry}.")
                [(kind, topic)] = entry.items()
                topic = " ".join(str(topic).split())
                if topic in self._plan:
                    raise ValueError(f"{self.deck}: {topic!r} is listed twice.")
                self._plan[topic] = (kind, level)
                self.topics.append(topic)
        # A profile written back out carries both; anything else is a mistake.
        if given and given != self.topics:
            raise ValueError(f"{self.deck}: give `topics` or `levels`, not both.")
        return self

    def kind_of(self, topic: str | None) -> tuple[str | None, int | None]:
        """The kind and level of one of this deck's topics; (None, None) for a
        deck written as a plain `topics` list, whose card_type decides."""
        return self._plan.get(topic or "", (None, None))

    @field_validator("deck")
    @classmethod
    def _normalise(cls, v: str) -> str:
        return "::".join(part.strip() for part in v.split("::"))

    @property
    def topics_per_day(self) -> int:
        return max(1, math.ceil(self.daily_quota / CARDS_PER_TOPIC))

    def quota_on(self, run_date: date) -> int:
        """Cards this deck wants on a day: a phased deck's first day can be a
        kickoff, bigger than the days after it."""
        if self.first_day_quota and run_date == self.start:
            return self.first_day_quota
        return self.daily_quota

    @property
    def _kickoff_topics(self) -> int:
        """Topics the start day covers."""
        quota = self.first_day_quota or self.daily_quota
        return max(1, math.ceil(quota / CARDS_PER_TOPIC))

    @property
    def last_day(self) -> date | None:
        """The day a phased deck writes its last topic."""
        if self.start is None or not self.topics or self.daily_quota <= 0:
            return None
        rest = max(0, len(self.topics) - self._kickoff_topics)
        return self.start + timedelta(days=math.ceil(rest / self.topics_per_day))

    def topics_on(self, run_date: date) -> list[str]:
        """A phased deck's topics for one day; empty outside its window."""
        day = (run_date - self.start).days if self.start else -1
        if day < 0:
            return []
        if day == 0:
            return self.topics[:self._kickoff_topics]
        first = self._kickoff_topics + (day - 1) * self.topics_per_day
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
            wanted = always + sum(t.quota_on(day) for t in running)
            if wanted > self.budget_on(day) and names not in seen:
                seen.add(names)
                problems.append(
                    f"From {day}, {' and '.join(names)} run together and want more than "
                    f"global_quota ({self.global_quota}) cards a day. Move a `start:` or "
                    "lower a `daily_quota`."
                )
            day += timedelta(days=1)
        return problems

    def budget_on(self, run_date: date) -> int:
        """The day's total: global_quota, plus a kickoff starting that day."""
        return self.global_quota + sum(
            t.first_day_quota - t.daily_quota for t in self.decks
            if t.first_day_quota and t.start == run_date and t.first_day_quota > t.daily_quota)

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
