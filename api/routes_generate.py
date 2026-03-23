import json
import logging

from fastapi import APIRouter, File, Form, UploadFile

from core import agents, embeddings, parsing
from core.cards import Card, GenerationRun
from storage import repository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["generate"])


@router.post("/generate")
async def generate_cards(
    topic: str = Form(...),
    count: int = Form(3),
    deck_type: str = Form("artwork"),
    file: UploadFile | None = File(None),
):
    """Run the 3-agent pipeline and return generated cards."""

    # 1. Get deck type config
    dt = repository.get_deck_type(deck_type)
    if not dt:
        return {"error": f"Unknown deck type: {deck_type}"}

    field_names = [f["name"] for f in dt.fields_schema]
    field_config = {f["name"]: f["type"] for f in dt.fields_schema}

    # 2. Get existing cards for context
    existing_cards, existing_embeddings = repository.get_existing_cards_with_embeddings(deck_type)
    existing_text = ", ".join(c.get("Title", "") for c in existing_cards if c.get("Title"))
    if not existing_text:
        existing_text = "No existing cards found."

    # 3. Handle file upload
    file_text = None
    if file:
        from core.ingestion import extract_text
        file_bytes = await file.read()
        file_text = extract_text(file_bytes, file.filename)

    # 4. Agent 1: Gap Analysis
    missing_concepts, persona = agents.analyze_knowledge_gaps(
        topic, existing_text, source_text=file_text, num=count
    )

    # 5. Agent 2: Generate Cards
    raw = agents.generate_cards(missing_concepts, count, field_config, persona=persona)
    parsed = parsing.smart_parse(raw, field_names)

    if not parsed:
        return {"error": "Generation failed", "raw_output": raw}

    # 6. Create run
    run = GenerationRun(
        topic=topic, deck_name=dt.name, deck_type=deck_type,
        persona=persona, total_generated=len(parsed),
    )
    run_id = repository.create_run(run)

    # 7. Save cards with embeddings + duplicate detection
    saved_cards = []
    for card_fields in parsed:
        # Check for duplicates
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
        card.id = card_id

        saved_cards.append({
            "id": card_id,
            "fields": card_fields,
            "status": status,
            "duplicate_reason": reason if is_dup else None,
        })

        # Add to existing set for within-batch dedup
        if not is_dup:
            existing_cards.append(card_fields)
            existing_embeddings.append(emb)

    return {
        "run_id": run_id,
        "persona": persona,
        "gap_analysis": missing_concepts,
        "cards": saved_cards,
    }
