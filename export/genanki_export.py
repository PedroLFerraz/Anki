import logging
from datetime import datetime
from pathlib import Path

import genanki

from core.cards import Card, DeckType
from core.config import EXPORTS_DIR, MEDIA_DIR

logger = logging.getLogger(__name__)

# Stable IDs (random but fixed so Anki recognizes updates on re-import)
ARTWORK_MODEL_ID = 1607392319
ARTWORK_DECK_ID = 2058400319


def _build_genanki_model(deck_type: DeckType, model_id: int) -> genanki.Model:
    """Build a genanki Model from a DeckType definition."""
    fields = [{"name": f["name"]} for f in deck_type.fields_schema]
    templates = [
        {
            "name": t.name,
            "qfmt": t.front,
            "afmt": t.back,
        }
        for t in deck_type.templates
    ]
    return genanki.Model(
        model_id,
        "Art-a7e12",  # Match the real model name from the user's deck
        fields=fields,
        templates=templates,
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
    model = _build_genanki_model(deck_type, ARTWORK_MODEL_ID)
    deck = genanki.Deck(ARTWORK_DECK_ID, deck_name)

    media_files = []
    field_names = [f["name"] for f in deck_type.fields_schema]

    for card in cards:
        fields = card.fields_json
        field_values = []

        for fname in field_names:
            value = fields.get(fname, "")

            # Image field: wrap in <img> tag if we have a downloaded file
            if fname == "Artwork" and card.image_filename:
                value = f'<img src="{card.image_filename}">'
                img_path = MEDIA_DIR / card.image_filename
                if img_path.exists():
                    media_files.append(str(img_path))

            field_values.append(str(value))

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
