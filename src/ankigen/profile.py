"""The prompt profile: who the learner is and what each run should produce."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

CardType = Literal["basic", "cloze", "detailed"]


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

    @field_validator("deck")
    @classmethod
    def _normalise(cls, v: str) -> str:
        return "::".join(part.strip() for part in v.split("::"))


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
        return problems


def load_profile(path: str | Path) -> Profile:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Profile.model_validate(data)
