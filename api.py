"""FastAPI web interface for the Anki flashcard generator."""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import storage.database  # triggers init_db()
from core import agents, embeddings, images
from core.apkg_import import import_apkg
from core.config import EXPORTS_DIR, MEDIA_DIR
from export.genanki_export import export_cards
from storage import repository

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

app = FastAPI(title="Anki Flashcard Generator")

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)


# --------------- Request models ---------------

class GenerateRequest(BaseModel):
    topic: str
    count: int = 5
    card_type: str = "basic"
    no_embeddings: bool = False


class StatusUpdate(BaseModel):
    status: str


class BatchStatusUpdate(BaseModel):
    ids: list[int]
    status: str


class CardUpdate(BaseModel):
    question: str
    answer: str
    extra_fields: dict | None = None


class ExportRequest(BaseModel):
    deck_name: str = "Flashcards"


# --------------- API endpoints ---------------

@app.get("/api/health")
def health():
    err = agents.check_llm_connection()
    if err:
        return {"status": "error", "error": err}
    return {"status": "ok"}


@app.get("/api/cards")
def list_cards(
    topic: str | None = None,
    status: str | None = None,
    card_type: str | None = None,
):
    cards = repository.get_cards(topic=topic, status=status)
    if card_type:
        cards = [c for c in cards if c.get("card_type") == card_type]
    return {"cards": cards}


@app.get("/api/cards/{card_id}")
def get_card(card_id: int):
    card = repository.get_card_by_id(card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    return card


@app.put("/api/cards/{card_id}")
def update_card(card_id: int, body: CardUpdate):
    card = repository.get_card_by_id(card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    repository.update_card_content(card_id, body.question, body.answer, body.extra_fields)
    return repository.get_card_by_id(card_id)


@app.delete("/api/cards/{card_id}")
def delete_card(card_id: int):
    if not repository.delete_card_by_id(card_id):
        raise HTTPException(404, "Card not found")
    return {"ok": True}


@app.patch("/api/cards/{card_id}/status")
def update_status(card_id: int, body: StatusUpdate):
    card = repository.get_card_by_id(card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    try:
        repository.update_card_status(card_id, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return repository.get_card_by_id(card_id)


@app.patch("/api/cards/batch-status")
def batch_update_status(body: BatchStatusUpdate):
    try:
        count = repository.update_cards_status_batch(body.ids, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"updated": count}


@app.post("/api/generate")
def generate(req: GenerateRequest):
    topic = req.topic.strip()
    if not topic:
        raise HTTPException(400, "Topic cannot be empty")
    if req.count <= 0:
        raise HTTPException(400, "Count must be greater than 0")
    if req.card_type not in ("basic", "detailed", "visual", "cloze"):
        raise HTTPException(400, f"Invalid card type: {req.card_type}")

    err = agents.check_llm_connection()
    if err:
        raise HTTPException(503, err)

    # Context for dedup
    ctx_cards, ctx_embeddings = repository.get_context_cards_with_embeddings()
    existing_text = "\n".join(
        f"Q: {c['Question']}" for c in ctx_cards if c.get("Question")
    )
    if not existing_text:
        existing_text = "(none)"

    # Generate via LLM
    cards = agents.generate_cards(topic, req.count, existing_text, card_type=req.card_type)
    if not cards:
        raise HTTPException(500, "Generation failed — no cards returned")

    # Dedup + save
    saved = []
    dedup_cards = list(ctx_cards)
    dedup_embeddings = list(ctx_embeddings)

    for card in cards:
        emb = None
        if not req.no_embeddings:
            emb = embeddings.get_embedding(f"{card['question']} {card['answer']}")

        is_dup, reason = embeddings.is_duplicate(
            card["question"], dedup_cards, dedup_embeddings, new_embedding=emb,
        )
        status = "DUPLICATE" if is_dup else "GENERATED"

        extra_fields = _build_extra_fields(card, req.card_type)

        card_id = repository.save_card(
            question=card["question"], answer=card["answer"],
            topic=topic, embedding=emb, status=status,
            card_type=req.card_type, extra_fields=extra_fields,
        )
        saved.append({"id": card_id, "is_dup": is_dup, "reason": reason,
                       "extra_fields": extra_fields, **card})

        if not is_dup:
            dedup_cards.append({"Question": card["question"], "Answer": card["answer"]})
            dedup_embeddings.append(emb)

    # Download images for detailed/visual (concurrent)
    if req.card_type in ("detailed", "visual"):
        non_dups = [c for c in saved if not c["is_dup"]]
        queries = [(c.get("image_query", ""), c["id"])
                   for c in non_dups if c.get("image_query")]
        if queries:
            results = images.search_and_download_batch(queries)
            for card in non_dups:
                filename = results.get(card["id"])
                if filename:
                    extra = card.get("extra_fields") or {}
                    extra["image_filename"] = filename
                    repository.update_card_extra_fields(card["id"], extra)

        # Visual cards without images are useless
        if req.card_type == "visual":
            for card in non_dups:
                db_card = repository.get_card_by_id(card["id"])
                ef = (db_card or {}).get("extra_fields", {})
                if not ef.get("image_filename"):
                    repository.update_card_status(card["id"], "REJECTED")

    # Return fresh data from DB
    result = [repository.get_card_by_id(c["id"]) for c in saved]
    return {"cards": [c for c in result if c]}


@app.get("/api/topics")
def list_topics():
    return {"topics": repository.get_topics()}


@app.get("/api/counts")
def get_counts(topic: str | None = None):
    return repository.get_card_counts(topic=topic)


@app.post("/api/export")
def export_apkg(req: ExportRequest):
    cards = repository.get_cards(status="ACCEPTED")
    if not cards:
        raise HTTPException(404, "No accepted cards to export")

    path = export_cards(cards, deck_name=req.deck_name)
    for c in cards:
        repository.update_card_status(c["id"], "EXPORTED")

    return FileResponse(
        str(path),
        media_type="application/octet-stream",
        filename=path.name,
    )


@app.post("/api/import")
async def import_context(file: UploadFile = File(...), clear_existing: bool = False):
    if not file.filename or not file.filename.endswith(".apkg"):
        raise HTTPException(400, "File must be an .apkg file")

    if clear_existing:
        repository.delete_context_cards()

    with tempfile.NamedTemporaryFile(suffix=".apkg", delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        deck_name, cards = import_apkg(tmp_path)
        if not cards:
            return {"count": 0, "deck_name": "Unknown"}
        count = repository.save_context_cards(cards, source=deck_name)
        return {"count": count, "deck_name": deck_name}
    except Exception as e:
        raise HTTPException(400, str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.delete("/api/clear")
def clear_cards(
    status: str = "GENERATED,REJECTED,DUPLICATE",
    topic: str | None = None,
):
    total = 0
    for s in status.split(","):
        total += repository.delete_cards_by_status(s.strip(), topic=topic)
    return {"deleted": total}


# --------------- Helpers ---------------

def _build_extra_fields(card: dict, card_type: str) -> dict | None:
    if card_type == "detailed":
        return {
            "summary": card.get("summary", ""),
            "explanation": card.get("explanation", ""),
            "image_query": card.get("image_query", ""),
        }
    elif card_type == "visual":
        return {
            "title": card.get("title", ""),
            "explanation": card.get("explanation", ""),
            "image_query": card.get("image_query", ""),
        }
    elif card_type == "cloze":
        return {
            "text": card.get("text", card.get("answer", "")),
            "extra": card.get("extra", ""),
        }
    return None


# --------------- Static files ---------------

app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))
