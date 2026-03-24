from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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

# Serve card media files
MEDIA_DIR = Path("data/media")
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")

# Serve web frontend (production build)
WEB_DIST = Path(__file__).parent / "web" / "dist"
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIST / "assets")), name="assets")

    @app.get("/{path:path}")
    async def serve_spa(request: Request, path: str):
        # Try static file first, then fall back to index.html for SPA routing
        file = WEB_DIST / path
        if file.is_file():
            return FileResponse(str(file))
        return FileResponse(str(WEB_DIST / "index.html"))
