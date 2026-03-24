from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import storage.database  # triggers init_db()

from api.routes_generate import router as generate_router
from api.routes_cards import router as cards_router
from api.routes_analytics import router as analytics_router

app = FastAPI(title="Anki Card Generator", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(generate_router)
app.include_router(cards_router)
app.include_router(analytics_router)


@app.get("/")
def root():
    return {"status": "ok", "message": "Anki Card Generator API v2.0"}
