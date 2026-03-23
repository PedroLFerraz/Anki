import json
import logging
from datetime import datetime
from pathlib import Path

import genanki

from core.cards import Card, DeckType
from core.config import EXPORTS_DIR, MEDIA_DIR

logger = logging.getLogger(__name__)

# Stable model IDs (random but fixed so Anki recognizes updates)
ARTWORK_MODEL_ID = 1607392319
ARTWORK_DECK_ID = 2058400319


def _build_genanki_model(deck_type: DeckType, model_id: int) -> genanki.Model:
    """Build a genanki Model from a DeckType definition."""
    fields = [{"name": f["name"]} for f in deck_type.fields_schema]
    return genanki.Model(
        model_id,
        deck_type.name.title() + " Card",
        fields=fields,
        templates=[
            {
                "name": deck_type.name.title() + " Layout",
                "qfmt": deck_type.front_template,
                "afmt": deck_type.back_template,
            }
        ],
        css=deck_type.css,
    )


def export_cards(
    cards: list[Card],
    deck_type: DeckType,
    deck_name: str = "Great Works of Art",
    output_filename: str | None = None,
) -> Path:
    """
    Export cards to an .apkg file.
    Returns the path to the generated file.
    """
    model_id = ARTWORK_MODEL_ID
    deck_id = ARTWORK_DECK_ID

    model = _build_genanki_model(deck_type, model_id)
    deck = genanki.Deck(deck_id, deck_name)

    media_files = []
    field_names = [f["name"] for f in deck_type.fields_schema]

    for card in cards:
        fields = card.fields_json
        field_values = []

        for fname in field_names:
            value = fields.get(fname, "")

            # Check if this field has an image
            if card.image_filename and fname == field_names[0]:
                # For artwork cards, the first field is the image field
                value = f'<img src="{card.image_filename}">'
                img_path = MEDIA_DIR / card.image_filename
                if img_path.exists():
                    media_files.append(str(img_path))

            # Check for audio — append sound tag to the Note field or last field
            if card.audio_filename and fname == field_names[-1]:
                value = f"{value} [sound:{card.audio_filename}]".strip()
                audio_path = MEDIA_DIR / card.audio_filename
                if audio_path.exists():
                    media_files.append(str(audio_path))

            field_values.append(value)

        note = genanki.Note(model=model, fields=field_values)
        deck.add_note(note)

    if not output_filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = deck_name.replace(" ", "_").lower()
        output_filename = f"{safe_name}_{timestamp}.apkg"

    output_path = EXPORTS_DIR / output_filename

    package = genanki.Package(deck)
    package.media_files = media_files
    package.write_to_file(str(output_path))

    logger.info("Exported %d cards to %s", len(cards), output_path)
    return output_path
