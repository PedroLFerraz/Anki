from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class Card(BaseModel):
    id: Optional[int] = None
    deck_type: str
    fields_json: dict
    image_filename: Optional[str] = None
    audio_filename: Optional[str] = None
    created_at: Optional[datetime] = None
    source_topic: Optional[str] = None
    run_id: Optional[int] = None
    status: str = "GENERATED"


class GenerationRun(BaseModel):
    run_id: Optional[int] = None
    timestamp: Optional[datetime] = None
    topic: str
    deck_name: str
    deck_type: str
    persona: Optional[str] = None
    total_generated: int = 0
    total_accepted: int = 0


class CardTemplate(BaseModel):
    name: str
    front: str
    back: str


class DeckType(BaseModel):
    name: str
    fields_schema: List[dict]  # [{"name": "Title", "type": "Text"}, ...]
    templates: List[CardTemplate]
    css: str
    anki_model_id: Optional[int] = None  # Real Anki model ID from imported .apkg
    anki_deck_id: Optional[int] = None   # Real Anki deck ID from imported .apkg
