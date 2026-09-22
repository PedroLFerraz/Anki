"""Generate stage: turn each request's prompt into cards.

This is the only non-deterministic stage. Everything downstream reads its
output from the warehouse, so retrying verify/dedup/export never re-calls the
model or changes which cards exist.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date

from ankigen import llm

logger = logging.getLogger(__name__)

CLOZE_PLAIN = re.compile(r"\{\{c\d+::(.*?)(?:::[^}]*)?\}\}")


@dataclass
class Card:
    front: str          # plain text, used for dedup and verification
    back: str
    fields: dict = field(default_factory=dict)  # note fields, keyed by card_types field name


def clean_field(text: str) -> str:
    """Strip stray formatting characters that small models produce."""
    text = re.sub(r"^[>=#@*•\-]+\s*", "", str(text).strip())
    return text.strip("*").strip()


def fix_cloze_syntax(text: str) -> str:
    """Repair the cloze markup models commonly get wrong."""
    text = re.sub(r"(?<!\{)\{(c\d+::.*?)\}(?!\})", r"{{\1}}", text)   # {c1::x}   -> {{c1::x}}
    text = re.sub(r"\{{3,}(c\d+::.*?)\}{3,}", r"{{\1}}", text)        # {{{c1::x}}} -> {{c1::x}}
    text = re.sub(r"\{\{(?!c\d+::)(.*?)\}\}", r"{{c1::\1}}", text)     # {{x}}     -> {{c1::x}}
    return text


def parse_cards(card_type: str, data: dict) -> list[Card]:
    raw = data.get("cards", []) if isinstance(data, dict) else []
    cards: list[Card] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue

        if card_type == "cloze":
            text = fix_cloze_syntax(clean_field(item.get("text", "")))
            extra = clean_field(item.get("extra", ""))
            if not CLOZE_PLAIN.search(text) or len(text) < 10:
                logger.warning("Skipping cloze without a valid deletion: %r", text[:60])
                continue
            plain = CLOZE_PLAIN.sub(r"\1", text)
            cards.append(Card(plain, text, {"Text": text, "Extra": extra}))

        elif card_type == "detailed":
            q = clean_field(item.get("question", ""))
            summary = clean_field(item.get("summary", ""))
            explanation = clean_field(item.get("explanation", ""))
            summary = summary or (explanation.split(". ")[0].rstrip(".") + "." if explanation else "")
            if len(q) < 5 or len(summary) < 3:
                logger.warning("Skipping low-quality detailed card: %r", q[:60])
                continue
            cards.append(Card(q, summary, {
                "Question": q, "Summary": summary, "Explanation": explanation or summary,
                "Image": "", "Reference": "",
            }))

        else:
            q = clean_field(item.get("question", ""))
            a = clean_field(item.get("answer", ""))
            if len(q) < 5 or len(a) < 2:
                logger.warning("Skipping low-quality card: Q=%r A=%r", q[:60], a[:40])
                continue
            cards.append(Card(q, a, {"Question": q, "Answer": a}))
    return cards


def generate_for_request(req: dict) -> tuple[list[Card], llm.LLMResult | None, int, int]:
    """Cards for one request. Tops up once if the model returns too few."""
    want = req["n"]
    cards: list[Card] = []
    result = None
    p_tok = c_tok = 0
    prompt = req["prompt"]

    for attempt in range(2):
        result = llm.call_json(prompt)
        p_tok += result.prompt_tokens
        c_tok += result.completion_tokens
        for card in parse_cards(req["card_type"], result.data):
            if card.front.lower() not in {c.front.lower() for c in cards}:
                cards.append(card)
        if len(cards) >= want:
            break
        already = "\n".join(f"- {c.front}" for c in cards)
        prompt = (
            f"{req['prompt']}\n\nYou already wrote these in this batch; do not repeat them:\n"
            f"{already}\nWrite exactly {want - len(cards)} more."
        )
    return cards[:want], result, p_tok, c_tok


GENERATED_COLUMNS = (
    "run_date", "card_uid", "request_id", "deck", "card_type", "front", "back",
    "fields_json", "model", "prompt_tokens", "completion_tokens",
)


def card_uid(run_date: date, request_id: str, front: str) -> str:
    return hashlib.sha1(f"{run_date}|{request_id}|{front.lower()}".encode()).hexdigest()[:16]


def run(wh, run_date: date, requests: list[dict]) -> dict:
    rows, failures = [], []
    total_prompt = total_completion = 0
    for req in requests:
        try:
            cards, result, p_tok, c_tok = generate_for_request(req)
        except Exception as e:  # one bad request must not sink the whole run
            logger.error("Request %s (%s) failed: %s", req["request_id"], req["deck"], e)
            failures.append({"request_id": req["request_id"], "deck": req["deck"], "error": str(e)})
            continue
        total_prompt += p_tok
        total_completion += c_tok
        # Tokens are attributed to the first card so per-request totals stay summable.
        for i, card in enumerate(cards):
            rows.append((
                run_date, card_uid(run_date, req["request_id"], card.front), req["request_id"],
                req["deck"], req["card_type"], card.front, card.back,
                json.dumps(card.fields, ensure_ascii=False), result.model if result else None,
                p_tok if i == 0 else 0, c_tok if i == 0 else 0,
            ))
    # Two requests can land on the same card; keep the first.
    seen, unique = set(), []
    for r in rows:
        if r[1] not in seen:
            seen.add(r[1])
            unique.append(r)
    wh.replace_partition("generated_cards", run_date, GENERATED_COLUMNS, unique)
    return {
        "cards": len(unique),
        "requested": sum(r["n"] for r in requests),
        "failed_requests": failures,
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
    }
