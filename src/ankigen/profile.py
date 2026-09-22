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
