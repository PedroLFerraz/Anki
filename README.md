# Anki Flashcard Generator

AI-powered Anki flashcard generator using a local LLM (Ollama). Generate, review, and export flashcards to `.apkg` from the command line — no Anki desktop needed during generation.

## Features

- 4 card types: basic Q&A, detailed (summary + explanation + image), visual (image front), and cloze
- DuckDuckGo image search with automatic download for detailed and visual cards
- Two-tier duplicate detection: fuzzy text matching + semantic embeddings
- Import existing `.apkg` decks as dedup context
- Export to `.apkg` — import directly into Anki via File > Import
- Works offline with Ollama (default) or with Gemini API (optional)

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install and start Ollama (https://ollama.com)
ollama pull phi4-mini
ollama pull nomic-embed-text

# 3. Generate cards
python cli.py generate "Python decorators" -n 5
```

Ollama must be running (`ollama serve`) before generating cards.

## Card Types

| Type | Front | Back | Images |
|------|-------|------|--------|
| `basic` | Question | Answer | No |
| `detailed` | Question | Summary + full explanation + image | Yes (optional) |
| `visual` | Image | Title + explanation | Yes (required) |
| `cloze` | Sentence with `{{c1::blank}}` | Full sentence revealed | No |

```bash
python cli.py generate "Neural networks" -n 5 --type basic
python cli.py generate "Neural networks" -n 5 --type detailed
python cli.py generate "Neural networks" -n 5 --type visual
```

Visual cards with no image found are automatically discarded (DuckDuckGo rate limits can cause this — retry later if needed).

## Commands

### `generate` — Create new cards

```bash
python cli.py generate "Topic" -n 5
python cli.py generate "Topic" -n 3 --type detailed
python cli.py generate "Topic" -n 5 --deck-name "My Deck"
python cli.py generate "Topic" -n 5 --no-embeddings   # skip embedding-based dedup
```

After generation you are prompted to accept all, pick individually, or discard. Accepted cards can be exported immediately.

| Flag | Default | Description |
|------|---------|-------------|
| `-n`, `--count` | 5 | Number of cards to generate |
| `--type` | `basic` | Card type: `basic`, `detailed`, `visual` |
| `-d`, `--deck-name` | `Flashcards` | Deck name written into the `.apkg` |
| `--no-embeddings` | off | Use fuzzy matching only, skip embedding calls |

### `list` — View cards in the database

```bash
python cli.py list
python cli.py list --topic "Neural networks"
python cli.py list --status ACCEPTED
python cli.py list --status CONTEXT        # show imported context cards
```

Card statuses: `GENERATED`, `ACCEPTED`, `REJECTED`, `DUPLICATE`, `EXPORTED`, `CONTEXT`.

### `export` — Export accepted cards to `.apkg`

```bash
python cli.py export
python cli.py export --deck-name "My Deck"
```

Output is written to `data/exports/`. Cards are marked `EXPORTED` after a successful export.

### `clear` — Remove cards from the database

```bash
python cli.py clear                              # removes GENERATED, REJECTED, DUPLICATE
python cli.py clear --status REJECTED            # specific status only
python cli.py clear --topic "Neural networks"    # scoped to a topic
python cli.py clear --all                        # removes everything including ACCEPTED and CONTEXT
```

### `import-context` — Load an existing deck for dedup

```bash
python cli.py import-context path/to/deck.apkg
python cli.py import-context path/to/deck.apkg --clear-existing
```

Cards from the imported deck are stored with status `CONTEXT` and used during duplicate detection. They are never exported.

### `clear-context` — Remove imported context cards

```bash
python cli.py clear-context
```

## Configuration

Copy `.env.example` to `.env` and edit as needed. All settings have defaults that work with Ollama out of the box.

```bash
cp .env.example .env
```

### Ollama (default — free, no rate limits)

```
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=phi4-mini
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

### Gemini (optional — requires API key)

```
LLM_PROVIDER=gemini
GOOGLE_API_KEY=your_key_here
```

Get a free Gemini API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). The free tier supports ~20 requests/day on `gemini-2.5-flash-lite`.

## Duplicate Detection

Cards are checked against both imported context and cards generated in the current session.

1. **Fuzzy matching** — always active, catches near-identical questions ("What is X?" vs "Define X")
2. **Semantic embeddings** — enabled by default, catches conceptually similar questions across different wording. Disable with `--no-embeddings` if you want faster generation without embedding calls.

## Project Structure

```
cli.py                   main CLI entry point — all commands
.env.example             template for environment configuration

core/
  agents.py              LLM prompt construction and card generation per type
  card_types.py          card type definitions: fields, templates, CSS, genanki model IDs
  apkg_import.py         parse existing .apkg files for context import
  embeddings.py          semantic duplicate detection using nomic-embed-text or Gemini
  images.py              DuckDuckGo image search and download with rate-limit backoff
  config.py              settings loaded from .env via pydantic-settings

storage/
  database.py            SQLite schema and migrations
  repository.py          all CRUD operations — never write raw SQL elsewhere

export/
  genanki_export.py      build genanki models and write .apkg files

data/                    runtime directory (gitignored)
  anki_generator.db      SQLite database
  exports/               generated .apkg files
  media/                 downloaded images
```

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) with `phi4-mini` and `nomic-embed-text` (default, free)
- Or a Gemini API key (alternative provider)
- No Anki desktop needed — only for the final File > Import step
