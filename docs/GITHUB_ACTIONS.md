# Running the daily pipeline without leaving a PC on

GitHub Actions runs the pipeline on GitHub's machines: each run gets a clean
Linux VM, does the work, and is destroyed. On a public repository the standard
runners are free, with no minute limit and no card on file, which makes this the
cheapest always-on option there is.

Because the runner cannot see your machine, everything it needs is either in the
repo or rebuilt on the spot:

| it needs | where it comes from |
|---|---|
| the code | cloned from this repo |
| your collection | `collection/collection.anki2`, committed |
| embeddings | `fastembed`, in-process — there is no Ollama on a runner |
| past runs | the warehouse, restored from the Actions cache |
| the cards | uploaded as a workflow artifact to download |

## Setup

One secret. In Settings → Secrets and variables → Actions, add
`GOOGLE_API_KEY` with your Gemini key.

Optionally set *variables* (not secrets) `GEMINI_MODEL` and `VERIFY_MODEL` to
change models without editing the workflow.

Then Actions → **daily cards** → Run workflow. After that it runs daily at
06:00 your time. Each run uploads the `.apkg` and the run report; download them
from the run's page and import into Anki.

## Keeping the collection current

The runner reads whatever was last committed, so refresh it after a heavy
study session:

```bash
ankigen sync-collection
git add collection/collection.anki2 && git commit -m "collection: refresh" && git push
```

`sync-collection` takes a proper snapshot, so it works with Anki open and
captures reviews still sitting in the `-wal` file.

It matters less than it sounds. The collection feeds the avoid list, the dedup
pool and weak-card selection, none of which move much in a week — a slightly
stale collection costs you a near-duplicate now and then, not a broken run.

## What to know

**Each refresh adds ~14MB to the repo permanently.** Git keeps every version
forever, so committing the collection weekly is about 700MB a year. If it gets
uncomfortable, the options are Git LFS, refreshing less often, or rewriting
history to drop old copies.

**Scheduled workflows stop after 60 days without a commit.** GitHub disables
them on dormant repositories, and does not tell you.

**The warehouse lives in the Actions cache**, restored at the start of a run and
saved at the end. Losing it is survivable — the next run rebuilds from the
collection — but the pipeline would forget which cards it has already made, and
re-embedding takes about a minute and a half. Caches are evicted after 7 days
unused, which a daily schedule prevents.

**It grows.** `raw_notes` stores a full snapshot of the collection per run date,
roughly 14MB a day. The warehouse wants a retention policy before this has been
running long.

**Gemini's free tier is 20 chat requests per day, per model.** Both
`GEMINI_MODEL` and `VERIFY_MODEL` therefore take a comma-separated preference
order, best model first; the run walks down it as models run out or return 503.
The checker is a different family from the writer on purpose — it doubles the
allowance, and a model marking its own homework shares its blind spots.
