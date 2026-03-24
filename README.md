# Anki Card Generator

AI-powered Anki flashcard generator. Uses a multi-agent system (Google Gemini) to analyze what you already know, identify knowledge gaps, and generate cards that match your existing deck format exactly.

Built for the **"Great Works of Art"** deck (724 artworks with Artist? and Title? templates), but designed to support any card type.

## How It Works

1. **Import** your existing deck so the system knows what you already have
2. **Generate** new cards — the AI picks an expert persona, finds gaps in your collection, and creates cards
3. **Review** the cards (duplicates are flagged automatically)
4. **Export** to `.apkg` and import into Anki

No Anki desktop or AnkiConnect needed during generation — cards are exported as `.apkg` files.

## Quick Start

```bash
# Install
pip3 install -r requirements.txt

# Add your Gemini API key
cp .env.example .env
# Edit .env and add your key

# Import your existing deck (one-time)
python3 cli.py import "Great Works of Art.apkg" --no-embeddings

# Generate new cards (2 API calls)
python3 cli.py generate "Baroque painting" --count 3 --no-embeddings

# List what was generated
python3 cli.py list

# Export accepted cards to .apkg
python3 cli.py export
```

Then open Anki and do **File > Import** on the `.apkg` file in `data/exports/`.

## CLI Commands

### `generate` — Create new cards

```bash
python3 cli.py generate "Impressionism" --count 5
python3 cli.py generate "Baroque" --count 3 --no-embeddings    # skip embedding API calls
python3 cli.py generate "Rococo" -n 2 -f notes.pdf             # use a PDF as source
```

The AI will:
- Pick an expert persona (e.g., "Art Historian specializing in Baroque Art")
- Analyze gaps against your existing 700+ cards
- Generate cards with all 15 fields matching your deck format
- Flag duplicates via fuzzy title matching (and optionally semantic embeddings)
- Prompt you to accept/reject, fetch images, and export

### `import` — Load an existing `.apkg` for dedup

```bash
python3 cli.py import "Great Works of Art.apkg"                 # with embeddings
python3 cli.py import "Great Works of Art.apkg" --no-embeddings  # faster, fuzzy dedup only
```

### `list` — View generated cards

```bash
python3 cli.py list                    # all cards
python3 cli.py list --status ACCEPTED  # only accepted
```

### `export` — Export to `.apkg`

```bash
python3 cli.py export                              # export ACCEPTED cards
python3 cli.py export --status GENERATED           # export all generated
python3 cli.py export --deck-name "My Art Deck"    # custom deck name
```

## API Server

There's also a FastAPI server for programmatic access (and future web frontend):

```bash
python3 -m uvicorn main:app --reload
# Swagger UI at http://localhost:8000/docs
```

Endpoints:
- `POST /api/generate` — generate cards
- `GET /api/cards` — list cards
- `PATCH /api/cards/{id}` — accept/reject
- `POST /api/export` — download `.apkg`
- `GET /api/deck-types` — available card types
- `GET /api/analytics` — generation stats

## Free Tier Usage

The project works with the **Gemini free tier** (20 requests/day on `gemini-2.5-flash-lite`):

- Each generation uses **2 API calls** (gap analysis + card generation)
- Use `--no-embeddings` to skip embedding calls (fuzzy title matching handles most duplicates)
- Automatic retry with backoff on rate limits (429 errors)
- That gives you ~10 generation runs per day on free tier

## Duplicate Detection

Two-tier system, no vector database needed:

1. **Fuzzy matching** (no API calls) — catches "Starry Night" vs "The Starry Night", "Composition VII" vs "Composition VIII"
2. **Semantic embeddings** (optional, uses API) — catches conceptually similar cards even with different titles

Import your existing deck first so the system knows what you already have.

## Project Structure

```
cli.py              — interactive CLI (main interface)
main.py             — FastAPI server

core/               — business logic (no framework dependencies)
  agents.py         — Gemini multi-agent system (gap analysis + card generation)
  embeddings.py     — semantic duplicate detection (Gemini embeddings)
  media.py          — Wikimedia/DuckDuckGo image search + parallel fetch
  parsing.py        — pipe-separated card text parser
  ingestion.py      — PDF/TXT file extraction
  apkg_import.py    — import existing .apkg decks
  config.py         — settings via .env

storage/            — data layer
  database.py       — SQLite schema + deck type definitions
  repository.py     — CRUD operations

export/             — output
  genanki_export.py — .apkg file generation (multi-template support)

api/                — FastAPI routes
  routes_generate.py
  routes_cards.py
  routes_analytics.py

data/               — runtime (gitignored)
  anki_generator.db — SQLite database
  exports/          — generated .apkg files
  media/            — downloaded images
```

## Deck Format

The artwork deck type matches the real "Great Works of Art" deck exactly:

**15 fields:** Artwork, Artist, Title, Subtitle/Alternate Titles, Title in Original Language, Date, Period/Movement, Medium, Nationality, Note, Image Source, Image copyright information, Permanent Location, Instructive Link(s), Gallery/Museum Link(s)

**2 card templates:** Artist? (shows artwork, asks who painted it) and Title? (shows artwork, asks the title)

## Requirements

- Python 3.10+
- Google Gemini API key ([get one free](https://aistudio.google.com/apikey))
- No Anki desktop needed for generation (only for final import)
