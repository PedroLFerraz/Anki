import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core import media
from core.cards import Card
from export.genanki_export import export_cards
from storage import repository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["cards"])


class CardUpdate(BaseModel):
    status: str  # ACCEPTED, REJECTED


class ExportRequest(BaseModel):
    card_ids: List[int]
    deck_name: str = "Great Works of Art"


@router.get("/cards")
def list_cards(deck_type: Optional[str] = None, status: Optional[str] = None):
    cards = repository.get_cards(deck_type=deck_type, status=status)
    return [
        {
            "id": c.id,
            "deck_type": c.deck_type,
            "fields": c.fields_json,
            "image_filename": c.image_filename,
            "audio_filename": c.audio_filename,
            "status": c.status,
            "source_topic": c.source_topic,
            "created_at": str(c.created_at) if c.created_at else None,
        }
        for c in cards
    ]


@router.patch("/cards/{card_id}")
def update_card(card_id: int, update: CardUpdate):
    repository.update_card_status(card_id, update.status)
    return {"id": card_id, "status": update.status}


@router.post("/cards/{card_id}/fetch-media")
def fetch_media_for_card(card_id: int, audio_lang: str = "en"):
    """Search and download image + generate audio for a card."""
    cards = repository.get_cards()
    card = next((c for c in cards if c.id == card_id), None)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    fields = card.fields_json
    result = {"image": None, "audio": None, "copyrighted": False}

    # Image: use Title + Artist for precise artwork search
    title = fields.get("Title", "")
    artist = fields.get("Artist", "")
    if title or artist:
        urls, is_verified = media.search_images(title=title, artist=artist)
        if urls:
            img_result = media.download_image(urls)
            if img_result:
                filename, _ = img_result
                repository.update_card_media(card_id, image_filename=filename)
                result["image"] = filename
                if not is_verified:
                    result["copyrighted"] = True

    # Audio: use artist name
    audio_text = fields.get("Artist", "") or fields.get("Title", "")
    if audio_text:
        audio_result = media.generate_audio(audio_text, lang=audio_lang)
        if audio_result:
            filename, _ = audio_result
            repository.update_card_media(card_id, audio_filename=filename)
            result["audio"] = filename

    return result


@router.delete("/cards/clear")
def clear_generated_cards(status: str = "GENERATED,REJECTED,DUPLICATE", deck_type: Optional[str] = None):
    """Clear generated/rejected/duplicate cards from previous sessions."""
    total = 0
    for s in status.split(","):
        count = repository.delete_cards_by_status(s.strip(), deck_type=deck_type)
        total += count
    return {"deleted": total}


@router.post("/export")
def export_to_apkg(req: ExportRequest):
    """Export accepted cards to .apkg file."""
    all_cards = repository.get_cards()
    selected = [c for c in all_cards if c.id in req.card_ids]

    if not selected:
        raise HTTPException(status_code=400, detail="No cards found for given IDs")

    deck_type_name = selected[0].deck_type
    dt = repository.get_deck_type(deck_type_name)
    if not dt:
        raise HTTPException(status_code=400, detail=f"Unknown deck type: {deck_type_name}")

    output_path = export_cards(selected, dt, deck_name=req.deck_name)

    # Mark as exported
    for c in selected:
        repository.update_card_status(c.id, "EXPORTED")

    return FileResponse(
        path=str(output_path),
        media_type="application/octet-stream",
        filename=output_path.name,
    )
