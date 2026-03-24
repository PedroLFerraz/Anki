from __future__ import annotations

import logging
import re
import time

from google import genai
from core.config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> genai.Client | None:
    global _client
    if not settings.google_api_key:
        return None
    if _client is None:
        _client = genai.Client(api_key=settings.google_api_key)
    return _client


def _generate_with_retry(client: genai.Client, prompt: str, max_retries: int = 3) -> str:
    """Generate content with automatic retry on rate limits."""
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=settings.gemini_model, contents=prompt
            )
            return response.text
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
    raise Exception("Max retries exceeded due to rate limiting")


def analyze_knowledge_gaps(
    topic: str,
    existing_cards_text: str,
    source_text: str | None = None,
    num: int = 3,
) -> tuple[str, str]:
    """
    Combined Agent 0+1: Identifies expert persona AND analyzes gaps in a single call.
    Returns (gap_analysis, persona).
    Saves 1 API call vs the previous 2-call approach.
    """
    client = _get_client()
    if not client:
        return "Error: No API Key", "Expert"

    if source_text:
        prompt = f"""
        You are an expert educator. First, determine the best expert persona for this topic,
        then perform a gap analysis AS that persona.

        TOPIC: "{topic}"
        SOURCE MATERIAL (first 500 chars): "{source_text[:500]}"

        SOURCE MATERIAL (Full):
        '''
        {source_text[:30000]}
        '''

        USER'S EXISTING CARDS:
        '''
        {existing_cards_text}
        '''

        TASK:
        1. First line: State your chosen expert persona (e.g., "PERSONA: Art History Professor")
        2. Then: Compare the SOURCE MATERIAL vs EXISTING CARDS and identify {num} concepts
           found in the SOURCE MATERIAL that are missing from the existing cards.

        RULES:
        1. ONLY suggest concepts actually present in the SOURCE MATERIAL.
        2. Ignore outside knowledge not in the text.

        OUTPUT FORMAT:
        PERSONA: [Job Title]
        [Bulleted list of {num} missing concepts]
        """
    else:
        prompt = f"""
        You are an expert educator. First, determine the best expert persona for this topic,
        then perform a gap analysis AS that persona.

        TOPIC: "{topic}"

        THE USER ALREADY KNOWS:
        '''
        {existing_cards_text}
        '''

        TASK:
        1. First line: State your chosen expert persona (e.g., "PERSONA: Art History Professor")
        2. Then: Identify {num} SPECIFIC "Knowledge Gaps" or new examples (e.g. Artworks)
           missing from the user's knowledge.

        RULES:
        1. Suggest advanced angles, edge cases, or comparisons specific to your field.
        2. Do NOT repeat what the user already knows.

        OUTPUT FORMAT:
        PERSONA: [Job Title]
        [Bulleted list of {num} missing concepts]
        """

    try:
        raw = _generate_with_retry(client, prompt).strip()

        # Parse persona from first line
        persona = "Expert Tutor"
        lines = raw.split("\n", 1)
        first_line = lines[0].strip()
        if first_line.upper().startswith("PERSONA:"):
            persona = first_line.split(":", 1)[1].strip().strip("*").strip()
            gap_analysis = lines[1].strip() if len(lines) > 1 else raw
        else:
            gap_analysis = raw

        return gap_analysis, persona
    except Exception as e:
        return f"Error analyzing gaps: {e}", "Expert"


def generate_cards(
    missing_concepts: str,
    num: int,
    field_config: dict[str, str],
    persona: str = "Expert Tutor",
) -> str:
    """Agent 2: The Content Creator. Returns raw pipe-separated card text."""
    client = _get_client()
    if not client:
        return "Error: No API Key"

    fields_list = list(field_config.keys())
    structure_example = "|".join(f"{f}" for f in fields_list)

    field_instructions = []
    for i, (f, f_type) in enumerate(field_config.items(), 1):
        if f_type == "Image":
            field_instructions.append(f"  {i}. {f}: 2-3 word image search query (NO URLs)")
        elif f_type == "(Skip)":
            field_instructions.append(f"  {i}. {f}: LEAVE EMPTY (just put nothing)")
        else:
            field_instructions.append(f"  {i}. {f}: Plain text")

    prompt = f"""
    You are a strict {persona}.

    TASK: Generate {num} Anki cards based on these MISSING CONCEPTS:
    '''
    {missing_concepts}
    '''

    STRICT FORMAT — each line must have EXACTLY {len(fields_list)} fields separated by {len(fields_list)-1} pipe characters "|":
    {structure_example}

    FIELD DEFINITIONS (you MUST include ALL {len(fields_list)} fields in order):
{chr(10).join(field_instructions)}

    RULES:
    1. Output raw lines ONLY — no numbering, no bullets, no markdown.
    2. Each line MUST have exactly {len(fields_list)-1} pipe "|" characters.
    3. For the 'Artist' field, ALWAYS provide FULL first and last name (e.g., 'Vincent van Gogh').
    4. DO NOT use the pipe character "|" inside any field value.
    5. Empty/skip fields still need their pipe separator (e.g., "...||..." for an empty field between two others).
    6. Write as a {persona} would.

    Output only the raw text lines, exactly {num} lines.
    """

    try:
        return _generate_with_retry(client, prompt)
    except Exception as e:
        return f"Error: {e}"
