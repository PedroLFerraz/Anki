# Running the daily pipeline without leaving a PC on

GitHub Actions runs the pipeline on GitHub's machines: each run gets a clean
Linux VM, does the work, and is destroyed. On a public repository the standard
runners are free, with no minute limit and no card on file, which makes this the
cheapest always-on option there is.

Because the runner cannot see your machine, everything it needs is fetched or
rebuilt on the spot:

| it needs | where it comes from |
|---|---|
| the code | cloned from this repo |
| your collection | synced down from AnkiWeb |
| embeddings | `fastembed`, in-process — there is no Ollama on a runner |
| past runs | the warehouse, restored from the Actions cache |
| the cards | synced back to AnkiWeb, and kept as an artifact |

Nothing is imported by hand: the run adds the cards to your collection and syncs
them up, and your phone and desktop pull them down like any other change.

## Setup

Two secrets, under Settings → Secrets and variables → Actions.

**`GOOGLE_API_KEY`** — your Gemini key.

**`ANKIWEB_KEY`** — a sync token, not your password. Get one locally:

```bash
pip install ".[push]"
ankigen push --login
```

It prints `ANKIWEB_KEY=...`. Add that as the secret, and put it in your local
`.env` too so `pull` and `push` work from your machine. Changing your AnkiWeb
password invalidates it.

Optionally set *variables* (not secrets) `GEMINI_MODEL` and `VERIFY_MODEL` to
change models without editing the workflow. Both take a comma-separated
preference order, best first.

Then Actions → **daily cards** → Run workflow. After that it runs daily at
06:00 your time.

## Running one deck on demand

The manual trigger takes four optional inputs: **deck**, **topic**, **prompt**
and **count**. Give a deck and it writes for that deck instead of the day's
plan; topic and prompt steer it further. The same thing locally:

```bash
ankigen run --deck "Data Platform::Kubernetes" --topic "probes" --prompt "Contrast what happens to traffic when each one fails."
```

## What to know

**The sync refuses to guess.** If AnkiWeb reports that the runner's copy and
yours have diverged beyond a normal merge, the job stops. Resolving that means
declaring one side the winner, and choosing the runner's could discard review
history. Sync from Anki on your own machine, then re-run; if it persists, clear
the `anki-collection-` cache so the next run starts from a fresh download.

**Scheduled workflows stop after 60 days without a commit.** GitHub disables
them on dormant repositories, and does not tell you.

**Caches can be evicted** after 7 days unused, which a daily schedule prevents.
Losing the collection cache costs a fresh download; losing the warehouse cache
costs about ninety seconds of re-embedding and the memory of which cards were
already made.

**Gemini's free tier is 20 chat requests per day, per model**, which is why both
model settings are chains. A run costs roughly ten calls plus one per image
checked.

**`raw_notes` grows** by a full collection snapshot per run date, about 14MB a
day. The warehouse wants a retention policy before this has been running long.
