from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path

import genanki

from core.card_types import CARD_TYPES
from core.config import EXPORTS_DIR, MEDIA_DIR

logger = logging.getLogger(__name__)


def _build_model(card_type_def: dict) -> genanki.Model:
    kwargs = {}
    if card_type_def.get("model_type"):
        kwargs["model_type"] = card_type_def["model_type"]
    return genanki.Model(
        card_type_def["model_id"],
        card_type_def["name"],
        fields=[{"name": f} for f in card_type_def["fields"]],
        templates=[{
            "name": "Card 1",
            "qfmt": card_type_def["template_front"],
            "afmt": card_type_def["template_back"],
        }],
        css=card_type_def["css"],
        **kwargs,
    )


def export_cards(cards: list[dict], deck_name: str = "Flashcards") -> Path:
    """Export cards to an .apkg file. Handles both basic and detailed card types.

    cards: list of dicts from repository.get_cards() with keys:
        question, answer, card_type, extra_fields (dict)
    """
    # Build models for each card type present
    types_used = set(c.get("card_type", "basic") for c in cards)
    models = {}
    for t in types_used:
        type_def = CARD_TYPES.get(t)
        if type_def:
            models[t] = _build_model(type_def)

    # Use a stable deck ID based on deck name (md5 avoids PYTHONHASHSEED randomisation)
    deck_id = int(hashlib.md5(deck_name.encode()).hexdigest(), 16) % (10**10)
    deck = genanki.Deck(deck_id, deck_name)

    media_files = []

    for card in cards:
        card_type = card.get("card_type", "basic")
        model = models.get(card_type)
        if not model:
            logger.warning("Unknown card type '%s', skipping card %s", card_type, card.get("id"))
            continue

        extra = card.get("extra_fields") or {}

        if card_type == "detailed":
            # Build image HTML
            image_html = ""
            image_filename = extra.get("image_filename")
            if image_filename:
                image_path = MEDIA_DIR / image_filename
                if image_path.exists():
                    image_html = f'<img src="{image_filename}">'
                    media_files.append(str(image_path))

            fields = [
                card["question"],
                extra.get("summary", card["answer"]),
                extra.get("explanation", ""),
                image_html,
                extra.get("reference", ""),
            ]
        elif card_type == "visual":
            image_html = ""
            image_filename = extra.get("image_filename")
            if image_filename:
                image_path = MEDIA_DIR / image_filename
                if image_path.exists():
                    image_html = f'<img src="{image_filename}">'
                    media_files.append(str(image_path))

            if not image_html:
                logger.warning("Visual card %s has no image, skipping export", card.get("id"))
                continue

            fields = [
                image_html,
                extra.get("title", card["question"]),
                extra.get("explanation", card["answer"]),
            ]
        elif card_type == "cloze":
            cloze_text = extra.get("text", card["answer"])
            if "{{c1::" not in cloze_text:
                logger.warning("Cloze card %s has no cloze markers, skipping export", card.get("id"))
                continue
            fields = [
                cloze_text,
                extra.get("extra", ""),
            ]
        else:
            # Basic: just Question, Answer
            fields = [card["question"], card["answer"]]

        note = genanki.Note(model=model, fields=fields)
        deck.add_note(note)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r'[<>:"/\\|?*]', '', deck_name).replace(" ", "_").lower()
    safe_name = safe_name or "deck"
    output_path = EXPORTS_DIR / f"{safe_name}_{timestamp}.apkg"

    package = genanki.Package(deck)
    package.media_files = media_files
    package.write_to_file(str(output_path))

    logger.info("Exported %d cards to %s", len(cards), output_path)
    return output_path
