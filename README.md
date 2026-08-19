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

### `providers` — Show LLM providers and test the configured one

```bash
python cli.py providers
```

Lists the available presets, prints the resolved generation and embedding
configuration (API keys masked), and probes the endpoint. Exits non-zero if the
provider is unreachable.

## Configuration

Copy `.env.example` to `.env` and edit as needed. All settings have defaults that work with Ollama out of the box.

```bash
cp .env.example .env
```

### Recommended setup (free)

**Groq for generation, local Ollama for embeddings.** Groq serves
`openai/gpt-oss-120b` free with no credit card — a much stronger model than
`phi4-mini`, and card quality is mostly a function of model quality. It has no
embeddings endpoint, so those fall back to Ollama automatically, where they are
free and unlimited.

1. Get a key at [console.groq.com/keys](https://console.groq.com/keys)
2. In `.env`:

```
LLM_PROVIDER=groq
LLM_API_KEY=your_key_here
```

3. Confirm it works:

```bash
python cli.py providers
```

That prints the resolved configuration and probes the endpoint, so a bad key or
a retired model ID shows up immediately rather than mid-generation.

### All presets

Every provider except Gemini speaks the OpenAI chat-completions protocol.

| Preset | Key from | Embeddings | Notes |
|---|---|---|---|
| `ollama` | — | Yes | Local, unlimited, offline. The default. |
| `groq` | [console.groq.com](https://console.groq.com/keys) | No | Recommended. `openai/gpt-oss-120b`, very fast. |
| `nvidia` | [build.nvidia.com](https://build.nvidia.com) | Yes | Serves both chat and embeddings. |
| `openrouter` | [openrouter.ai](https://openrouter.ai/keys) | No | Many free models, low per-model daily caps. |
| `sambanova` | [cloud.sambanova.ai](https://cloud.sambanova.ai) | No | Daily token budget, not a request cap. |
| `mistral` | [console.mistral.ai](https://console.mistral.ai) | Yes | Free tier is monthly credits. |
| `gemini` | [aistudio.google.com](https://aistudio.google.com/apikey) | Yes | Uses google-genai, not the OpenAI protocol. |

Free-tier limits and model IDs move constantly — Groq had already retired
`llama-3.3-70b-versatile` by the time this table was written. Treat it as a
starting point, verify with `python cli.py providers`, and override `LLM_MODEL`
if a preset has gone stale.
[awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis) tracks
current numbers.

Any other OpenAI-compatible endpoint works without a preset:

```
LLM_PROVIDER=custom
LLM_BASE_URL=https://your-endpoint/v1
LLM_MODEL=some-model
LLM_API_KEY=your_key_here
```

Models that reject `response_format` are detected on first use and fall back to
extracting JSON from the reply text, so JSON-mode support is not a requirement.

### Embeddings are configured separately

Most free chat APIs serve no embedding endpoint, so `EMBEDDING_PROVIDER` is its
own setting. Left empty it derives automatically: the chat provider if it
supports embeddings, otherwise local Ollama.

That makes the practical setup a hosted model for generation plus Ollama for
embeddings — generation gets a decent model, dedup stays free and unlimited:

```
LLM_PROVIDER=groq
LLM_API_KEY=your_key_here
# EMBEDDING_PROVIDER left empty -> local Ollama
```

With no embeddings reachable at all, generation still works and dedup falls back
to fuzzy text matching. That catches near-identical wording but not rephrasings,
and the first failure logs a one-time warning.

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
