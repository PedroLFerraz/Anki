"""Export stage: write the day's kept cards as an .apkg, plus a run report.

Cards land in `AnkiGen Inbox::<deck>` so they never mix into a deck unreviewed:
triage happens in Anki itself (study, edit, or delete), then move the keepers.

Note GUIDs derive from the card's uid, so importing the same day's package
twice updates the notes instead of duplicating them.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from pathlib import Path

import genanki

from ankigen.card_types import CARD_TYPES
from ankigen.targeting import INBOX
from ankigen.verify import UNVERIFIED

logger = logging.getLogger(__name__)


def _model(card_type: str) -> genanki.Model:
    spec = CARD_TYPES[card_type]
    kwargs = {"model_type": spec["model_type"]} if spec.get("model_type") else {}
    return genanki.Model(
        spec["model_id"], spec["name"],
        fields=[{"name": f} for f in spec["fields"]],
        templates=[{"name": "Card 1", "qfmt": spec["template_front"], "afmt": spec["template_back"]}],
        css=spec["css"],
        **kwargs,
    )


def _deck_id(name: str) -> int:
    # md5 rather than hash(): stable across processes regardless of PYTHONHASHSEED.
    return int(hashlib.md5(name.encode()).hexdigest(), 16) % (10**10)


def _tag(text: str) -> str:
    return "_".join(text.split())


def build_package(run_date: date, cards: list[dict]) -> genanki.Package | None:
    if not cards:
        return None
    models = {t: _model(t) for t in {c["card_type"] for c in cards}}
    decks: dict[str, genanki.Deck] = {}

    for c in cards:
        name = f"{INBOX}::{c['deck']}"
        deck = decks.setdefault(name, genanki.Deck(_deck_id(name), name))
        spec_fields = CARD_TYPES[c["card_type"]]["fields"]
        values = json.loads(c["fields_json"])
        tags = ["ankigen", f"ankigen::run_{run_date}", f"ankigen::{c['request_reason']}"]
        if (c.get("verify_reason") or "").startswith(UNVERIFIED):
            tags.append("ankigen::unverified")
        deck.add_note(genanki.Note(
            model=models[c["card_type"]],
            fields=[str(values.get(f, "")) for f in spec_fields],
            guid=genanki.guid_for(c["card_uid"]),
            tags=[_tag(t) for t in tags],
        ))
    return genanki.Package(list(decks.values()))


def run(wh, run_date: date, out_root: str | Path) -> dict:
    out_dir = Path(out_root) / str(run_date)
    out_dir.mkdir(parents=True, exist_ok=True)

    kept = wh.query(
        "SELECT * FROM card_outcomes WHERE run_date = ? AND outcome = 'kept' ORDER BY deck, card_uid",
        [run_date],
    )
    apkg = out_dir / f"ankigen_{run_date}.apkg"
    apkg.unlink(missing_ok=True)  # a rerun that keeps nothing must not leave a stale package
    package = build_package(run_date, kept)
    if package:
        package.write_to_file(str(apkg))
    return {"kept": len(kept), "apkg": str(apkg) if package else None}


def write_report(wh, run_date: date, out_root: str | Path) -> dict:
    """Its own final stage: runs after export has finished, so every earlier
    stage's timing and status is final when the report is written."""
    out_dir = Path(out_root) / str(run_date)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(wh, run_date)
    apkg = out_dir / f"ankigen_{run_date}.apkg"
    report["apkg"] = str(apkg) if apkg.exists() else None
    path = out_dir / "run_report.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return {"report": str(path), "outcomes": report["outcomes"]}


def build_report(wh, run_date: date) -> dict:
    """Built only from the warehouse, so it works when stages ran as separate tasks."""
    outcomes = wh.query(
        "SELECT outcome, COUNT(*) AS n FROM card_outcomes WHERE run_date = ? GROUP BY outcome",
        [run_date],
    )
    by_deck = wh.query(
        """SELECT deck, COUNT(*) FILTER (WHERE outcome = 'kept') AS kept,
                  COUNT(*) AS generated
           FROM card_outcomes WHERE run_date = ? GROUP BY deck ORDER BY deck""",
        [run_date],
    )
    dropped = wh.query(
        """SELECT deck, front, outcome,
                  CASE outcome WHEN 'dropped_verify' THEN verify_reason ELSE dup_reason END AS reason
           FROM card_outcomes WHERE run_date = ? AND outcome LIKE 'dropped_%'
           ORDER BY outcome, deck""",
        [run_date],
    )
    stages = wh.query(
        """SELECT stage, status, rows_out, detail,
                  date_diff('millisecond', started_at, finished_at) / 1000.0 AS seconds
           FROM pipeline_runs WHERE run_date = ? AND stage != 'report' ORDER BY started_at""",
        [run_date],
    )
    details = {}
    for st in stages:
        details[st["stage"]] = json.loads(st.pop("detail") or "{}")
    generated = details.get("generate", {})
    return {
        "run_date": str(run_date),
        "outcomes": {r["outcome"]: r["n"] for r in outcomes},
        "by_deck": by_deck,
        "dropped": dropped,
        "tokens": {
            "prompt": generated.get("prompt_tokens", 0),
            "completion": generated.get("completion_tokens", 0),
        },
        "stages": stages,
        "stage_details": details,
    }
