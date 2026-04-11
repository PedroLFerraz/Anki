from __future__ import annotations

import json
import logging
import re
import time

from core.config import settings

logger = logging.getLogger(__name__)

_gemini_client = None
_ollama_client = None


def _get_gemini_client():
    global _gemini_client
    if not settings.google_api_key:
        return None
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=settings.google_api_key)
    return _gemini_client


def _get_ollama_client():
    global _ollama_client
    if _ollama_client is None:
        from openai import OpenAI
        _ollama_client = OpenAI(base_url=settings.ollama_base_url, api_key="ollama")
    return _ollama_client


def _generate_json(prompt: str, max_retries: int = 3) -> dict:
    """Generate JSON content with automatic retry on rate limits and parse errors."""
    provider = settings.llm_provider

    for attempt in range(max_retries):
        try:
            if provider == "gemini":
                from google.genai import types
                client = _get_gemini_client()
                if not client:
                    raise Exception("No GOOGLE_API_KEY configured")
                response = client.models.generate_content(
                    model=settings.gemini_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                    ),
                )
                return json.loads(response.text)
            else:
                client = _get_ollama_client()
                response = client.chat.completions.create(
                    model=settings.ollama_model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                )
                return json.loads(response.choices[0].message.content)
        except json.JSONDecodeError as e:
            logger.warning("JSON parse failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                continue
            raise
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                match = re.search(r"retryDelay.*?(\d+)s", error_str)
                wait = int(match.group(1)) + 2 if match else 30 * (attempt + 1)
                logger.info("Rate limited. Waiting %ds before retry %d/%d...", wait, attempt + 1, max_retries)
                print(f"  Rate limited. Waiting {wait}s before retry {attempt + 1}/{max_retries}...")
                time.sleep(wait)
            else:
                raise
    raise Exception("Max retries exceeded")


def _clean_field(text: str) -> str:
    """Strip stray formatting characters that small models produce."""
    text = re.sub(r'^[>=#@*•\-]+\s*', '', text.strip())
    return text.strip('*').strip()


def generate_cards(topic: str, num: int, existing_cards_text: str, card_type: str = "basic") -> list[dict]:
    """Generate flashcards for a topic. Retries if model returns fewer than requested."""

    if card_type == "visual":
        gen_fn = _generate_visual
    elif card_type == "detailed":
        gen_fn = _generate_detailed
    else:
        gen_fn = _generate_basic
    all_cards = []
    remaining = num
    max_attempts = 3

    for attempt in range(max_attempts):
        cards = gen_fn(topic, remaining, existing_cards_text)
        all_cards.extend(cards)
        remaining = num - len(all_cards)
        if remaining <= 0:
            break
        logger.info("Got %d/%d cards, retrying for %d more (attempt %d/%d)",
                     len(all_cards), num, remaining, attempt + 1, max_attempts)
        # Add already-generated questions to existing text to avoid repeats
        for c in cards:
            existing_cards_text += f"\nQ: {c.get('question', '')}"

    return all_cards[:num]


def _generate_basic(topic: str, num: int, existing_cards_text: str) -> list[dict]:
    prompt = f"""You are an expert educator creating Anki flashcards.

TOPIC: "{topic}"

THE USER ALREADY HAS THESE CARDS:
'''
{existing_cards_text}
'''

Generate exactly {num} new flashcards about this topic.

RULES:
1. Each card must test ONE specific, concrete concept.
2. Questions should be clear and directly answerable.
3. Answers should be concise (1-3 sentences).
4. Do NOT repeat concepts the user already has.
5. Use plain text only — no markdown, no special characters.

Respond with JSON:
{{
  "cards": [
    {{"question": "What is ...?", "answer": "It is ..."}},
    {{"question": "How does ...?", "answer": "It works by ..."}}
  ]
}}"""

    try:
        result = _generate_json(prompt)
        cards = result.get("cards", [])
        if not isinstance(cards, list):
            return []

        cleaned = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            q = _clean_field(str(card.get("question", "")))
            a = _clean_field(str(card.get("answer", "")))
            if len(q) < 5 or len(a) < 3:
                logger.warning("Skipping low-quality card: Q=%r A=%r", q, a)
                continue
            cleaned.append({"question": q, "answer": a})
        return cleaned
    except Exception as e:
        logger.error("Card generation failed: %s", e)
        return []


def _generate_detailed(topic: str, num: int, existing_cards_text: str) -> list[dict]:
    prompt = f"""You are an expert educator creating detailed Anki flashcards with rich explanations.

TOPIC: "{topic}"

THE USER ALREADY HAS THESE CARDS:
'''
{existing_cards_text}
'''

Generate exactly {num} new detailed flashcards. Every card MUST have ALL 4 fields:
- question: A clear, specific question
- summary: A bold one-line summary that directly answers the question
- explanation: A 2-4 sentence explanation with more depth
- image_query: 2-4 words to search for a relevant diagram or illustration (REQUIRED for every card)

EXAMPLE:
{{
  "cards": [
    {{
      "question": "Explain the bias-variance tradeoff",
      "summary": "Reducing Bias Increases Variance (and vice-versa)",
      "explanation": "Reducing error (with more model complexity) generally results in higher sensitivity to changes in training data and worse generalization (overfitting). The optimal model complexity balances both sources of error.",
      "image_query": "bias variance tradeoff diagram"
    }}
  ]
}}

RULES:
1. Each card must cover ONE specific concept.
2. The summary should be a direct, concise answer (one line).
3. The explanation adds depth — not just a longer version of the summary.
4. image_query should describe a useful diagram, chart, or illustration.
5. Do NOT repeat concepts the user already has.
6. Use plain text only — no markdown.

Respond with JSON:
{{
  "cards": [
    {{
      "question": "...",
      "summary": "...",
      "explanation": "...",
      "image_query": "..."
    }}
  ]
}}"""

    try:
        result = _generate_json(prompt)
        cards = result.get("cards", [])
        if not isinstance(cards, list):
            return []

        cleaned = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            q = _clean_field(str(card.get("question", "")))
            summary = _clean_field(str(card.get("summary", "")))
            explanation = _clean_field(str(card.get("explanation", "")))
            image_query = _clean_field(str(card.get("image_query", "")))

            # Fallbacks for missing fields
            if not summary and explanation:
                summary = explanation.split(".")[0] + "."
            if not explanation and summary:
                explanation = summary
            if not image_query:
                # Derive from question: take key nouns
                image_query = re.sub(r'\b(what|how|why|when|is|are|the|a|an|in|of|and|does|do|explain|describe)\b', '', q.lower(), flags=re.IGNORECASE)
                image_query = " ".join(image_query.split()[:4]).strip("? ")

            if len(q) < 5 or len(summary) < 3:
                logger.warning("Skipping low-quality detailed card: Q=%r S=%r", q, summary)
                continue

            cleaned.append({
                "question": q,
                "answer": summary,  # stored in DB answer column for dedup
                "summary": summary,
                "explanation": explanation,
                "image_query": image_query,
            })
        return cleaned
    except Exception as e:
        logger.error("Detailed card generation failed: %s", e)
        return []


def _generate_visual(topic: str, num: int, existing_cards_text: str) -> list[dict]:
    prompt = f"""You are creating visual recognition flashcards. The front shows an image, the back reveals what it is.

TOPIC: "{topic}"

THE USER ALREADY HAS THESE CARDS:
'''
{existing_cards_text}
'''

Generate exactly {num} concepts from this topic that can be VISUALLY IDENTIFIED from a diagram, chart, photo, or illustration.

Each card MUST have ALL 3 fields:
- title: The name of the concept (what the image shows)
- explanation: ONE short sentence (max 15 words) explaining what it is
- image_query: 2-4 specific words to find a good diagram or photo of this concept

EXAMPLE:
{{
  "cards": [
    {{
      "title": "Confusion Matrix",
      "explanation": "Table showing true/false positives and negatives for classifier evaluation.",
      "image_query": "confusion matrix diagram"
    }}
  ]
}}

RULES:
1. Pick concepts that are VISUALLY DISTINCTIVE — someone should be able to recognize them from an image.
2. Good examples: diagrams, charts, anatomical structures, architectural patterns, chemical structures, maps.
3. Bad examples: abstract ideas with no visual form.
4. Do NOT repeat concepts the user already has.
5. Use plain text only.

Respond with JSON:
{{
  "cards": [
    {{
      "title": "...",
      "explanation": "...",
      "image_query": "..."
    }}
  ]
}}"""

    try:
        result = _generate_json(prompt)
        cards = result.get("cards", [])
        if not isinstance(cards, list):
            return []

        cleaned = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            title = _clean_field(str(card.get("title", "")))
            explanation = _clean_field(str(card.get("explanation", "")))
            image_query = _clean_field(str(card.get("image_query", "")))

            if not image_query:
                image_query = title.lower() + " diagram"

            if len(title) < 3 or len(explanation) < 10:
                logger.warning("Skipping low-quality visual card: T=%r E=%r", title, explanation)
                continue

            cleaned.append({
                "question": title,      # DB question column (for dedup)
                "answer": explanation,   # DB answer column
                "title": title,
                "explanation": explanation,
                "image_query": image_query,
            })
        return cleaned
    except Exception as e:
        logger.error("Visual card generation failed: %s", e)
        return []
