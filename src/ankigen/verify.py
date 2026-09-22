"""Verify stage: a second LLM pass that fact-checks each generated card.

Cards are checked in batches per request, so a run costs one extra call per
request rather than per card.

If the checker itself fails (rate limit, outage) cards pass through marked
`unverified` instead of being dropped: they land in the Anki inbox for human
triage anyway, and a flaky checker shouldn't zero out a day's run. The run
report and the note tags make the difference visible.
"""
from __future__ import annotations

import logging
from datetime import date
from importlib import resources
from string import Template

from ankigen import llm
from ankigen.profile import Profile

logger = logging.getLogger(__name__)

PASS_SCORE = 0.7
UNVERIFIED = "unverified"


def build_prompt(deck: str, level: str, cards: list[dict]) -> str:
    template = Template(resources.files("ankigen.prompts").joinpath("verify.txt").read_text(encoding="utf-8"))
    listing = "\n".join(
        f"{i}. Q: {c['front']}\n   A: {c['back']}" for i, c in enumerate(cards, start=1)
    )
    return template.substitute(level=level, deck=deck, cards=listing)


def judge(results: list, cards: list[dict]) -> list[tuple[bool, float | None, str]]:
    """Map the checker's verdicts back onto cards by index."""
    by_index = {}
    for r in results if isinstance(results, list) else []:
        if isinstance(r, dict) and isinstance(r.get("index"), int):
            by_index[r["index"]] = r

    verdicts = []
    for i, _ in enumerate(cards, start=1):
        r = by_index.get(i)
        if r is None:
            verdicts.append((True, None, f"{UNVERIFIED}: checker skipped this card"))
            continue
        correct = bool(r.get("correct", False))
        answerable = bool(r.get("answerable", True))
        try:
            score = float(r.get("score", 0))
        except (TypeError, ValueError):
            score = 0.0
        issue = str(r.get("issue") or "").strip()
        passed = correct and answerable and score >= PASS_SCORE
        if passed:
            reason = ""
        elif not correct:
            reason = f"incorrect: {issue or 'factual error'}"
        elif not answerable:
            reason = f"unanswerable: {issue or 'ambiguous question'}"
        else:
            reason = f"low quality ({score:.2f}): {issue}".rstrip(": ")
        verdicts.append((passed, score, reason))
    return verdicts


def run(wh, run_date: date, profile: Profile) -> dict:
    cards = wh.query(
        "SELECT card_uid, request_id, deck, front, back FROM generated_cards "
        "WHERE run_date = ? ORDER BY request_id, card_uid",
        [run_date],
    )
    rows = []
    checker_errors = 0

    if not profile.verify:
        rows = [(run_date, c["card_uid"], True, None, "verification disabled") for c in cards]
    else:
        batches: dict[str, list[dict]] = {}
        for c in cards:
            batches.setdefault(c["request_id"], []).append(c)
        for batch in batches.values():
            try:
                result = llm.call_json(build_prompt(batch[0]["deck"], profile.learner.level, batch))
                verdicts = judge(result.data.get("results", []), batch)
            except Exception as e:
                logger.warning("Verification failed for %d card(s): %s", len(batch), e)
                checker_errors += 1
                verdicts = [(True, None, f"{UNVERIFIED}: {e}")] * len(batch)
            rows.extend(
                (run_date, c["card_uid"], passed, score, reason)
                for c, (passed, score, reason) in zip(batch, verdicts)
            )

    wh.replace_partition(
        "verified_cards", run_date, ("run_date", "card_uid", "passed", "score", "reason"), rows
    )
    dropped = [r for r in rows if not r[2]]
    return {
        "checked": len(rows),
        "passed": len(rows) - len(dropped),
        "dropped": len(dropped),
        "unverified": sum(1 for r in rows if (r[4] or "").startswith(UNVERIFIED)),
        "checker_errors": checker_errors,
    }
