# AnkiGen

A daily batch pipeline that reads your Anki collection and writes new cards
that fit it. The cards match the phrasing of cards you already study, avoid what
you already know, re-teach what you keep forgetting, and are fact-checked before
they reach you. You steer it with one YAML profile.

It is also built the way a data platform team would build it: idempotent stages
keyed by date, a layered DuckDB warehouse, and output as Parquet. That makes it
ready to schedule with Airflow, containerise, and move to S3 and Kubernetes. See
the [roadmap](#roadmap).

```
Anki collection ──snapshot──▶ ingest ─▶ target ─▶ generate ─▶ verify ─▶ dedup ─▶ export ─▶ report
 (never touched)                │         │          │          │         │         │
                                └────────── DuckDB warehouse, one partition per run_date ─────┘
                                                                                    │
                                          data/out/<date>/ankigen_<date>.apkg ◀──────┤
                                          data/curated/<table>/run_date=<date>/*.parquet
```

## Quick start

```bash
pip install .                      # installs the `ankigen` command
cp .env.example .env               # set LLM_PROVIDER / LLM_API_KEY (Groq is free)
ankigen decks                      # see your decks, to write the profile
ankigen validate                   # check profiles/default.yaml against them
ankigen plan                       # what today's run would generate + the exact prompt
ankigen run                        # do it
ankigen report                     # what was kept, dropped, and why
```

Import `data/out/<date>/ankigen_<date>.apkg` into Anki with File > Import. New
cards land in **`AnkiGen Inbox::<deck>`**, tagged `ankigen::run_<date>`. Study
them there, delete what you don't want, and move the rest into the real deck.
Re-importing the same day's package updates those notes instead of duplicating
them.

Close Anki desktop before running. While it's open, Anki holds the collection
exclusively.

## What each stage does

| Stage | Reads | Writes | Notes |
|---|---|---|---|
| **ingest** | your `collection.anki2` | `raw_notes` (daily snapshot), `raw_revlog` (incremental) | Snapshots through SQLite's backup API, so reviews still in the `-wal` file are included. A plain file copy misses them, and there's a test proving it. Handles both schema generations and any note type, from `Front/Back` to `Frente/Verso`. |
| **target** | `raw_notes`, profile | `requests` (with the rendered prompt) | Deterministic. The same date always produces the same plan, and topics and weak cards rotate day to day. No LLM calls, so `plan` is instant. |
| **generate** | `requests` | `generated_cards` | The only non-deterministic stage. If one request fails, the rest of the run still goes ahead. |
| **verify** | `generated_cards` | `verified_cards` | A second LLM pass fact-checks each card. If the checker itself is down, cards pass through tagged `ankigen::unverified` instead of being dropped. |
| **dedup** | the above + `raw_notes` + previous runs | `dedup_results` | Fuzzy wording match, plus embedding similarity to catch rephrasings. Embeddings are cached by content hash, and only targeted decks are embedded. |
| **export** | `card_outcomes` view | `.apkg`, Parquet | Stable note GUIDs and stable deck and note-type IDs. |
| **report** | `pipeline_runs` + all of the above | `run_report.json` | Per-stage timings, drops with reasons, and token usage. |

Every stage replaces its own `run_date` partition in a single transaction.
Re-running any stage for any date is therefore safe. Retrying `dedup` or
`export` never calls the model and never changes which cards exist.

```bash
ankigen run --date 2026-09-22 --stage dedup --stage export --stage report
```

## The profile

`profiles/default.yaml` is where personalisation lives:

```yaml
learner:
  level: "working data scientist, moving into data platform"
  goals: ["Interview-ready on core data science: statistics, SQL, ML"]
style:
  max_answer_words: 40
  examples_per_prompt: 4          # few-shot examples drawn from YOUR cards
  rules: ["When a concept has a common misconception, target it."]
weak_cards: {min_lapses: 2, max_ease: 2100, max_per_deck: 1}
global_quota: 15
decks:
  - deck: DS::SQL                 # existing deck: extend it in your own voice
    daily_quota: 3
    topics: [window functions, NULL semantics]
    instructions: Use small SQL snippets in backticks.
  - deck: Data Platform::Airflow  # a subject you don't have yet
    new_deck: true
    topics: [idempotent tasks and safe backfills]
```

Every generation prompt is built from:

- your learner profile and style rules;
- a few real cards from that deck as examples, so new cards match your phrasing and length;
- the existing cards most related to today's topic, as a do-not-duplicate list (unrelated cards are left out to save tokens);
- for weak cards, the card you keep failing, with an instruction to approach it from a different angle rather than rephrase it.

`ankigen plan --prompts 3` prints exactly what will be sent.

## LLM providers

Any OpenAI-compatible endpoint works. Set `LLM_PROVIDER` to a preset (`groq`,
`nvidia`, `openrouter`, `sambanova`, `mistral`, `ollama`) or to `gemini`.
**Groq is the recommended free option.** It has no embeddings endpoint, so dedup
embeddings fall back to local Ollama (`ollama pull nomic-embed-text`) on their
own. If no embedding provider is reachable, dedup uses fuzzy matching only.
`ankigen providers` shows the resolved configuration and tests the connection.

## Development

```bash
pip install -e ".[dev]"
python -m pytest
```

The tests build real SQLite collections in both Anki schemas and replace the LLM
and embedding provider with deterministic fakes, so they run offline in a few
seconds.

> **Non-ASCII paths:** an editable install can't be built from a directory whose
> path contains characters outside the system codepage, because setuptools
> writes a `.pth` file in that encoding. pytest is configured with
> `pythonpath = ["src"]`, and `python -m ankigen` works with `PYTHONPATH=src`.

## Roadmap

1. ✅ **Core pipeline**: personalised, verified, deduplicated daily cards.
2. **Docker**: multi-stage image; the collection and profile mounted read-only.
3. **Airflow**: `ankigen_daily` DAG, one task per stage, `catchup` for backfills.
4. **AWS free tier**: S3 `raw/`, `curated/` and `gold/` layers via Terraform, and a least-privilege IAM role.
5. **Kubernetes**: `CronJob` on `kind`, then `KubernetesPodOperator` per stage.
6. Later: PDF ingestion as a second source, hosted deployment, and the Android client (see branch `archive/android-web`).
