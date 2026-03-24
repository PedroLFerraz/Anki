import logging

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

from core import agents, embeddings, parsing
from core.cards import Card, GenerationRun
from storage import repository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["generate"])


class GenerateRequest(BaseModel):
    topic: str
    count: int = 3
    deck_type: str = "artwork"


@router.post("/generate")
def generate_cards(req: GenerateRequest):
    """Run the 3-agent pipeline and return generated cards."""

    # 1. Get deck type config
    dt = repository.get_deck_type(req.deck_type)
    if not dt:
        return {"error": f"Unknown deck type: {req.deck_type}"}

    field_names = [f["name"] for f in dt.fields_schema]
    field_config = {f["name"]: f["type"] for f in dt.fields_schema}

    # 2. Get existing cards for context
    existing_cards, existing_embeddings = repository.get_existing_cards_with_embeddings(req.deck_type)
    existing_text = ", ".join(c.get("Title", "") for c in existing_cards if c.get("Title"))
    if not existing_text:
        existing_text = "No existing cards found."

    # 4. Agent 1: Gap Analysis
    missing_concepts, persona = agents.analyze_knowledge_gaps(
        req.topic, existing_text, num=req.count
    )

    # 5. Agent 2: Generate Cards
    raw = agents.generate_cards(missing_concepts, req.count, field_config, persona=persona)
    parsed = parsing.smart_parse(raw, field_names)

    if not parsed:
        return {"error": "Generation failed", "raw_output": raw}

    # 6. Create run
    run = GenerationRun(
        topic=req.topic, deck_name=dt.name, deck_type=req.deck_type,
        persona=persona, total_generated=len(parsed),
    )
    run_id = repository.create_run(run)

    # 7. Save cards with embeddings + duplicate detection
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
