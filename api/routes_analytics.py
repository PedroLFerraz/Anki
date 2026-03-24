from typing import Optional

from fastapi import APIRouter

from storage import repository

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/analytics")
def get_analytics(deck_type: Optional[str] = None):
    return repository.get_analytics(deck_type=deck_type)


@router.get("/deck-types")
def list_deck_types():
    types = repository.get_all_deck_types()
    return [
        {
            "name": t.name,
            "fields": t.fields_schema,
        }
        for t in types
    ]
