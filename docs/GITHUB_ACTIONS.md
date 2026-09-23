# Running the daily pipeline without leaving a PC on

GitHub Actions runs the pipeline on GitHub's machines: each run gets a clean
Linux VM, does the work, and is destroyed. On a public repository the standard
runners are free with no minute limit and no card on file, which makes this the
cheapest always-on option available.

The awkward part is not compute, it is that the pipeline reads *your* Anki
collection. This repo is public, and a collection is personal data, so it lives
in a separate private repo that the workflow clones at the start of each run.

## Setup

You need three secrets. Everything else is already in the workflow.

**1. A private repo for the collection**

Create an empty private repository — `anki-collection` will do — and put your
collection in it:

```bash
cp "$APPDATA/Anki2/Usuário 1/collection.anki2" .
git add collection.anki2 && git commit -m "collection" && git push
```

It is 14MB, well inside GitHub's limits. Close Anki first so the file is not
mid-write.

**2. A token that can read it**

Create a [fine-grained personal access token](https://github.com/settings/tokens?type=beta)
scoped to **only that repository**, with **Contents: Read**. Nothing else. If it
leaks it can read your flashcards and nothing more.

**3. The secrets**

In this repo, under Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `COLLECTION_REPO` | `PedroLFerraz/anki-collection` |
| `COLLECTION_TOKEN` | the token from step 2 |
| `GOOGLE_API_KEY` | your Gemini key |

Optionally set *variables* (not secrets) `GEMINI_MODEL` and `VERIFY_MODEL` to
change models without editing the workflow.

## Running it

Actions → daily cards → **Run workflow**. It runs daily at 06:00 your time
after that. Each run uploads the `.apkg` and the run report as an artifact;
download it from the run's page and import it into Anki.

## What to know

**Artifacts on a public repo are public.** Anyone can download the generated
cards and the run report. The collection itself is never uploaded — it stays in
the private repo — but the cards the run produces are visible. They are
flashcards about SQL and Kubernetes, so this is probably fine; it is worth
knowing rather than discovering.

**The collection goes stale.** The runner uses whatever you last pushed. That
matters less than it sounds: the collection feeds the avoid list, the dedup
pool and weak-card selection, none of which change much in a week. Push it
again when you have studied a lot, or when new cards have been imported.

**Scheduled workflows stop after 60 days without a commit.** GitHub disables
them on dormant repositories, silently. A commit re-enables it.

**The warehouse lives in the Actions cache**, restored at the start of each run
and saved at the end. Losing it is survivable — the next run rebuilds from the
collection — but the pipeline would forget which cards it has already made, and
re-embedding takes about a minute and a half. Caches are evicted after 7 days
unused, which a daily schedule keeps at bay.

**It grows.** `raw_notes` stores a full snapshot of the collection per run date,
about 14MB a day. The warehouse will need a retention policy before this has
been running for long.
