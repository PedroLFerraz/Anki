# AnkiGen — Android client

A Jetpack Compose front end for the Python backend in the repository root. It
talks to the FastAPI server over HTTP and writes finished cards **directly into
AnkiDroid**, so there is no `.apkg` export/import step on mobile.

## Why a thin client

Generation needs Ollama (or Gemini), image search, embeddings, and genanki —
none of which belong on a phone. The app is a UI plus an AnkiDroid bridge; the
backend keeps doing the work it already does and is already tested.

```
Phone (Kotlin/Compose)                    PC or VPS (Python)
┌──────────────────────┐                 ┌───────────────────────┐
│ Generate / Cards /   │  HTTP  ────────▶ │ FastAPI (api.py)      │
│ Settings             │ ◀────── JSON    │  ├─ Ollama / Gemini    │
│                      │                 │  ├─ image search       │
│ AnkiDroidExporter    │                 │  └─ SQLite            │
└──────────┬───────────┘                 └───────────────────────┘
           │ AddContentApi
           ▼
     AnkiDroid collection
```

## Running it

**1. Start the backend so the phone can reach it.** Binding to `0.0.0.0` is what
makes it visible beyond localhost:

```bash
python -m uvicorn api:app --host 0.0.0.0 --port 8000
```

**2. Point the app at it.** Open **Settings** in the app and set the server URL:

| Where the app runs | URL |
|---|---|
| Emulator | `http://10.0.2.2:8000` (the default — this is the host machine) |
| Real device on the same Wi-Fi | `http://<your-PC-LAN-IP>:8000`, e.g. `http://192.168.1.42:8000` |

Find the LAN IP with `ipconfig` on Windows (IPv4 Address of your Wi-Fi adapter).
Tap **Test connection** to confirm both the server and the LLM are reachable.

**3. Install AnkiDroid** from Google Play or F-Droid. The app asks for the
`READ_WRITE_DATABASE` permission the first time you send cards.

## Building

Requires JDK 17+ (Android Studio's bundled JBR works) and SDK platform 36.

```bash
./gradlew :app:assembleDebug
```

The debug APK lands in `app/build/outputs/apk/debug/`.

### Path caveat

This repository sits under a directory containing a non-ASCII character
(`U+2800`). AGP refuses such paths by default, so `gradle.properties` sets
`android.overridePathCheck=true`. The build works, but the Gradle **wrapper
script** cannot resolve its own classpath through that path — `./gradlew` fails
with `ClassNotFoundException: GradleWrapperMain`. Two ways around it:

- Open the `android/` folder in Android Studio, which uses its own Gradle launcher.
- Or invoke a Gradle distribution directly instead of the wrapper script.

Moving the project to an ASCII-only path (like the sibling
`~/AndroidStudioProjects/`) removes both problems.

## What the screens do

- **Generate** — topic, card type, count. Results arrive as a reviewable list;
  accept or reject individually or in bulk, then push the accepted ones to
  AnkiDroid in one tap.
- **Cards** — everything on the server, filterable by status, type, and topic.
  Multi-select for bulk accept/reject, or send a selection to AnkiDroid.
- **Settings** — server URL, connection test, target deck, AnkiDroid status, and
  collection counts.

## Known limitations

**Images are not transferred to AnkiDroid.** They live on the backend's
filesystem and notes are created from text fields only. Detailed cards keep
their summary and explanation; visual cards fall back to title plus
explanation. The app reports how many cards were affected after each send.
Lifting this means adding media support in `AnkiDroidExporter.send()`.

**Cloze notes use a standard note type.** `addNewCustomModel` cannot set a note
type's cloze flag, so cloze cards are sent as a two-field note with the blanks
masked on the front (`The [...] is the powerhouse`) and revealed on the back.
It reviews the same way; it just is not a native Anki cloze note.

**No offline cache.** Every screen reads through the network. A Room cache would
be the natural next addition.

## Layout

```
data/
  model/Models.kt          DTOs mirroring the Python repository, plus the
                           front/back text rules per card type
  remote/AnkiGenApi.kt     Retrofit interface, 1:1 with api.py routes
  remote/ApiClient.kt      Retrofit builder (rebuilds when the URL changes)
                           and error-to-message mapping
  local/SettingsStore.kt   server URL, deck name, cached AnkiDroid model IDs
  anki/AnkiDroidExporter.kt  AddContentApi bridge
  CardRepository.kt        single entry point to the backend

ui/
  theme/Theme.kt           palette shared with the web frontend
  components/CardItem.kt   one card, used by both list screens
  generate/                topic input, generation, review, send
  cards/                   filtering, multi-select, bulk actions
  settings/                server config, connection test, counts
```
