import logging

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

from core import agents, embeddings, media, parsing
from core.cards import Card, GenerationRun
from storage import repository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["generate"])


def _fetch_image_for_artwork(card_id: int, artwork: dict, fields: dict) -> str | None:
    """Download image for an artwork card, using Wikidata URL when available.

    Returns filename or None.
    """
    image_url = artwork.get("image_url") or fields.get("Image Source", "")
    title = fields.get("Title", "")
    artist = fields.get("Artist", "")

    # Try Wikidata URL directly first (fastest, most reliable)
    if image_url:
        result = media.download_image(image_url)
        if result:
            filename, _ = result
            repository.update_card_media(card_id, image_filename=filename)
            return filename

    # Fall back to multi-source search
    if title or artist:
        urls, _ = media.search_images(title=title, artist=artist)
        if urls:
            result = media.download_image(urls)
            if result:
                filename, _ = result
                repository.update_card_media(card_id, image_filename=filename)
                return filename

    return None


class GenerateRequest(BaseModel):
    topic: str
    count: int = 3
    deck_type: str = "artwork"


class ArtistRequest(BaseModel):
    artist_name: str
    deck_type: str = "artwork"
    limit: int = 0


@router.post("/generate")
def generate_cards(req: GenerateRequest):
    """Generate cards. Artwork decks use Wikidata; other decks use LLM."""

    dt = repository.get_deck_type(req.deck_type)
    if not dt:
        return {"error": f"Unknown deck type: {req.deck_type}"}

    # Artwork decks: use Wikidata (no LLM, no hallucinations)
    if req.deck_type == "artwork":
        from core.wikidata import query_artworks_by_topic, artworks_to_card_fields, base_title

        artworks = query_artworks_by_topic(req.topic, limit=req.count)
        if not artworks:
            return {"error": f"No artworks found on Wikidata for '{req.topic}'"}

        existing_cards = repository.get_cards(deck_type=req.deck_type)
        existing_titles = {base_title(c.fields_json.get("Title", "")) for c in existing_cards}
        new_artworks = [a for a in artworks if base_title(a["title"]) not in existing_titles]

        if not new_artworks:
            return {
                "cards": [],
                "message": "All artworks are already in the deck",
                "total_found": len(artworks),
                "skipped": len(artworks),
            }

        card_fields_list = artworks_to_card_fields(new_artworks)
        saved_cards = []
        for i, (art, fields) in enumerate(zip(new_artworks, card_fields_list)):
            card = Card(
                deck_type=req.deck_type, fields_json=fields,
                source_topic=req.topic, status="GENERATED",
            )
            card_id = repository.save_card(card)

            # Auto-fetch image
            img_filename = _fetch_image_for_artwork(card_id, art, fields)
            logger.info("[%d/%d] %s → %s", i + 1, len(new_artworks),
                        fields.get("Title", "?"), img_filename or "no image")

            saved_cards.append({
                "id": card_id,
                "fields": fields,
                "status": "GENERATED",
                "has_free_image": bool(fields.get("Image Source")),
                "image_filename": img_filename,
            })

        return {
            "cards": saved_cards,
            "total_found": len(artworks),
            "skipped": len(artworks) - len(new_artworks),
            "new": len(new_artworks),
        }

    # Non-artwork decks: LLM pipeline
    field_names = [f["name"] for f in dt.fields_schema]
    field_config = {f["name"]: f["type"] for f in dt.fields_schema}

    existing_cards, existing_embeddings = repository.get_existing_cards_with_embeddings(req.deck_type)
    existing_text = ", ".join(c.get("Title", "") for c in existing_cards if c.get("Title"))
    if not existing_text:
        existing_text = "No existing cards found."

    missing_concepts, persona = agents.analyze_knowledge_gaps(
        req.topic, existing_text, num=req.count
    )

    raw = agents.generate_cards(missing_concepts, req.count, field_config, persona=persona)
    parsed = parsing.smart_parse(raw, field_names)

    if not parsed:
        return {"error": "Generation failed", "raw_output": raw}

    run = GenerationRun(
        topic=req.topic, deck_name=dt.name, deck_type=req.deck_type,
        persona=persona, total_generated=len(parsed),
    )
    run_id = repository.create_run(run)

    saved_cards = []
    for card_fields in parsed:
        card_text = embeddings.card_text_for_embedding(card_fields)
        emb = embeddings.get_embedding(card_text)
        is_dup, reason = embeddings.is_duplicate(
            card_fields, existing_cards, existing_embeddings, new_embedding=emb
        )

        status = "DUPLICATE" if is_dup else "GENERATED"
        card = Card(
            deck_type=req.deck_type, fields_json=card_fields,
            source_topic=req.topic, run_id=run_id, status=status,
        )
        card_id = repository.save_card(card, embedding=emb)

        saved_cards.append({
            "id": card_id,
            "fields": card_fields,
            "status": status,
            "duplicate_reason": reason if is_dup else None,
        })

        if not is_dup:
            existing_cards.append(card_fields)
            existing_embeddings.append(emb)

    return {
        "run_id": run_id,
        "persona": persona,
        "gap_analysis": missing_concepts,
        "cards": saved_cards,
    }


@router.post("/generate/artist")
def generate_from_artist(req: ArtistRequest):
    """Look up real paintings by artist on Wikidata and create cards."""
    from core.wikidata import query_artist_artworks, artworks_to_card_fields, base_title

    dt = repository.get_deck_type(req.deck_type)
    if not dt:
        return {"error": f"Unknown deck type: {req.deck_type}"}

    artworks = query_artist_artworks(req.artist_name)
    if not artworks:
        return {"error": f"No artworks found on Wikidata for '{req.artist_name}'"}

    if req.limit > 0:
        artworks = artworks[:req.limit]

    # Filter out paintings already in the deck (fuzzy title match)
    existing_cards = repository.get_cards(deck_type=req.deck_type)
    existing_titles = {base_title(c.fields_json.get("Title", "")) for c in existing_cards}

    new_artworks = [a for a in artworks if base_title(a["title"]) not in existing_titles]

    if not new_artworks:
        return {
            "cards": [],
            "message": "All paintings from this artist are already in the deck",
            "total_found": len(artworks),
            "skipped": len(artworks),
        }

    card_fields_list = artworks_to_card_fields(new_artworks, req.artist_name)

    # Save cards + auto-fetch images
    saved_cards = []
    for i, (art, fields) in enumerate(zip(new_artworks, card_fields_list)):
        card = Card(
            deck_type=req.deck_type, fields_json=fields,
            source_topic=req.artist_name, status="GENERATED",
        )
        card_id = repository.save_card(card)

        # Auto-fetch image
        img_filename = _fetch_image_for_artwork(card_id, art, fields)
        logger.info("[%d/%d] %s → %s", i + 1, len(new_artworks),
                    fields.get("Title", "?"), img_filename or "no image")

        saved_cards.append({
            "id": card_id,
            "fields": fields,
            "status": "GENERATED",
            "has_free_image": bool(fields.get("Image Source")),
            "image_filename": img_filename,
        })

    return {
        "cards": saved_cards,
        "total_found": len(artworks),
        "skipped": len(artworks) - len(new_artworks),
        "new": len(new_artworks),
    }


@router.post("/generate/from-file")
async def generate_from_file(
    topic: str,
    count: int = 3,
    deck_type: str = "artwork",
    file: UploadFile = File(...),
):
    """Generate cards from an uploaded file."""
    from core.ingestion import extract_text

    dt = repository.get_deck_type(deck_type)
    if not dt:
        return {"error": f"Unknown deck type: {deck_type}"}

    field_names = [f["name"] for f in dt.fields_schema]
    field_config = {f["name"]: f["type"] for f in dt.fields_schema}

    existing_cards, existing_embeddings = repository.get_existing_cards_with_embeddings(deck_type)
    existing_text = ", ".join(c.get("Title", "") for c in existing_cards if c.get("Title"))
    if not existing_text:
        existing_text = "No existing cards found."

    file_bytes = await file.read()
    file_text = extract_text(file_bytes, file.filename)

    missing_concepts, persona = agents.analyze_knowledge_gaps(
        topic, existing_text, source_text=file_text, num=count
    )

    raw = agents.generate_cards(missing_concepts, count, field_config, persona=persona)
    parsed = parsing.smart_parse(raw, field_names)

    if not parsed:
        return {"error": "Generation failed", "raw_output": raw}

    run = GenerationRun(
        topic=topic, deck_name=dt.name, deck_type=deck_type,
        persona=persona, total_generated=len(parsed),
    )
    run_id = repository.create_run(run)

    saved_cards = []
    for card_fields in parsed:
        card_text = embeddings.card_text_for_embedding(card_fields)
        emb = embeddings.get_embedding(card_text)
        is_dup, reason = embeddings.is_duplicate(
            card_fields, existing_cards, existing_embeddings, new_embedding=emb
        )

        status = "DUPLICATE" if is_dup else "GENERATED"
        card = Card(
            deck_type=deck_type, fields_json=card_fields,
            source_topic=topic, run_id=run_id, status=status,
        )
        card_id = repository.save_card(card, embedding=emb)

        saved_cards.append({
            "id": card_id,
            "fields": card_fields,
            "status": status,
            "duplicate_reason": reason if is_dup else None,
        })

        if not is_dup:
            existing_cards.append(card_fields)
            existing_embeddings.append(emb)

    return {
        "run_id": run_id,
        "persona": persona,
        "gap_analysis": missing_concepts,
        "cards": saved_cards,
    }
