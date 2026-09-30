"""Give the command cards already in the collection what new ones are written
with: what each piece of the command does, under the answer.

The breakdown goes into the note's own Note field rather than a field of its
own. A new field would change the note type, which Anki can only sync one way,
over whichever side loses; appending to a field is an ordinary edit.

Written by the writer's model, checked by the checker's, one batch of notes per
request. A note whose breakdown the checker faults is left as it was, and the
next run asks again.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import resources
from string import Template

from ankigen import llm
from ankigen.config import settings
from ankigen.generate import parse_parts, parts_html, parts_text
from ankigen.ingest import strip_html

logger = logging.getLogger(__name__)

NOTETYPE = "AnkiGen Command"
MARK = 'class="ankigen-parts"'
BATCH = 10


@dataclass
class Item:
    nid: int
    deck: str
    task: str
    command: str
    parts: list[tuple[str, str]] | None = None
    issue: str = ""


def missing(col, deck: str | None = None) -> list[Item]:
    """Command notes without a breakdown, oldest first."""
    notetype = col.models.by_name(NOTETYPE)
    if not notetype:
        return []
    items = []
    for nid in sorted(col.models.nids(notetype)):
        note = col.get_note(nid)
        if MARK in note["Note"]:
            continue
        home = col.decks.name(note.cards()[0].did) if note.cards() else ""
        if deck and not (home == deck or home.startswith(deck + "::")):
            continue
        items.append(Item(nid, home, strip_html(note["Task"]), strip_html(note["Command"])))
    return items


def _prompt(name: str, **values) -> str:
    text = resources.files("ankigen.prompts").joinpath(name).read_text(encoding="utf-8")
    return Template(text).substitute(**values)


def _by_index(data) -> dict:
    found = data if isinstance(data, list) else (data or {}).get("results", [])
    return {r.get("index"): r for r in found if isinstance(r, dict)}


def write(items: list[Item], level: str) -> list[Item]:
    """Fill in each item's parts, keeping only the ones the checker passes."""
    checker = settings.resolve_verify()
    for start in range(0, len(items), BATCH):
        batch = items[start:start + BATCH]
        listing = "\n".join(f"{i}. Task: {it.task}\n   Answer: {it.command}"
                            for i, it in enumerate(batch, start=1))
        try:
            written = _by_index(llm.call_json(_prompt("parts.txt", level=level,
                                                      cards=listing)).data)
        except Exception as e:
            logger.warning("Could not write parts for %d note(s): %s", len(batch), e)
            continue
        for i, it in enumerate(batch, start=1):
            it.parts = parse_parts(written.get(i, {}).get("parts")) or None

        drafted = [it for it in batch if it.parts]
        listing = "\n".join(f"{i}. {it.command}\n   Parts: {parts_text(it.parts)}"
                            for i, it in enumerate(drafted, start=1))
        try:
            verdicts = _by_index(llm.call_json(_prompt("parts_check.txt", cards=listing),
                                               cfg=checker).data)
        except Exception as e:
            # Unchecked is not good enough for something a beginner trusts.
            logger.warning("Could not check parts for %d note(s): %s", len(drafted), e)
            for it in drafted:
                it.parts, it.issue = None, f"unchecked: {e}"
            continue
        for i, it in enumerate(drafted, start=1):
            verdict = verdicts.get(i, {})
            if verdict.get("correct") is not True:
                it.parts, it.issue = None, str(verdict.get("issue") or "no verdict")
    return items


def apply(col, items: list[Item]) -> int:
    """Append each checked breakdown to its note. Returns how many changed."""
    changed = 0
    for it in items:
        if not it.parts:
            continue
        note = col.get_note(it.nid)
        if MARK in note["Note"]:
            continue
        note["Note"] = note["Note"] + parts_html(it.parts)
        col.update_note(note)
        changed += 1
    return changed
