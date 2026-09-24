"""Export stage: write the day's kept cards as an .apkg, plus a run report.

Cards go straight into their target deck, tagged `ankigen::run_<date>`, so
nothing has to be moved afterwards. Set `inbox:` in the profile to park them in
a subdeck instead. A whole batch can be found (or deleted) later by its tag.

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
from ankigen.dedup import NEAR_DUP
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


def _with_image(card_type: str, values: dict, filename: str | None) -> dict:
    """Put the illustration where the note type can show it.

    `detailed` has a dedicated Image field. `basic` and `cloze` don't, so the
    tag is appended to the answer side, which is what Anki renders anyway.
    """
    if not filename:
        return values
    img = f'<img src="{filename}">'
    values = dict(values)
    if card_type == "detailed":
        values["Image"] = img
    elif card_type == "cloze":
        # Not .lstrip("<br>"): that strips *characters*, and ate the first
        # letter of any hint beginning with b or r.
        extra = values.get("Extra", "")
        values["Extra"] = f"{extra}<br>{img}" if extra else img
    else:
        values["Answer"] = f"{values.get('Answer', '')}<br>{img}"
    return values


def build_package(run_date: date, cards: list[dict], profile=None,
                  media_dir: Path | None = None) -> genanki.Package | None:
    if not cards:
        return None
    models = {t: _model(t) for t in {c["card_type"] for c in cards}}
    decks: dict[str, genanki.Deck] = {}
    media: list[str] = []

    for c in cards:
        name = profile.deck_for(c["deck"]) if profile else c["deck"]
        deck = decks.setdefault(name, genanki.Deck(_deck_id(name), name))
        spec_fields = CARD_TYPES[c["card_type"]]["fields"]
        values = json.loads(c["fields_json"])

        filename = c.get("image_filename")
        if filename and media_dir and (media_dir / filename).exists():
            values = _with_image(c["card_type"], values, filename)
            media.append(str(media_dir / filename))
        elif filename:
            logger.warning("Image %s is missing from %s; exporting without it", filename, media_dir)

        tags = ["ankigen", f"ankigen::run_{run_date}", f"ankigen::{c['request_reason']}"]
        if (c.get("verify_reason") or "").startswith(UNVERIFIED):
            tags.append("ankigen::unverified")
        if (c.get("dup_reason") or "").startswith(NEAR_DUP):
            # Close to something you already have, but not close enough to bin
            # unseen. Search `tag:ankigen::near-dup` in Anki to judge them.
            tags.append("ankigen::near-dup")
        deck.add_note(genanki.Note(
            model=models[c["card_type"]],
            fields=[str(values.get(f, "")) for f in spec_fields],
            guid=genanki.guid_for(c["card_uid"]),
            tags=[_tag(t) for t in tags],
        ))

    package = genanki.Package(list(decks.values()))
    package.media_files = sorted(set(media))
    return package


def run(wh, run_date: date, out_root: str | Path, profile=None,
        media_dir: Path | None = None) -> dict:
    out_dir = Path(out_root) / str(run_date)
    out_dir.mkdir(parents=True, exist_ok=True)

    kept = wh.query(
        "SELECT * FROM card_outcomes WHERE run_date = ? AND outcome = 'kept' ORDER BY deck, card_uid",
        [run_date],
    )
    apkg = out_dir / f"ankigen_{run_date}.apkg"
    apkg.unlink(missing_ok=True)  # a rerun that keeps nothing must not leave a stale package
    package = build_package(run_date, kept, profile, media_dir)
    if package:
        package.write_to_file(str(apkg))
    return {
        "kept": len(kept),
        "apkg": str(apkg) if package else None,
        "images": len(package.media_files) if package else 0,
    }


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
        "images": wh.query(
            """SELECT COUNT(*) FILTER (WHERE filename IS NOT NULL) AS found, COUNT(*) AS wanted
               FROM card_images WHERE run_date = ?""", [run_date])[0],
        "tokens": {
            "prompt": generated.get("prompt_tokens", 0),
            "completion": generated.get("completion_tokens", 0),
        },
        "stages": stages,
        "stage_details": details,
    }
