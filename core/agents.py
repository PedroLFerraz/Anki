import logging
import google.generativeai as genai
from core.config import settings

logger = logging.getLogger(__name__)

MODEL_NAME = settings.gemini_model


def _configure():
    if not settings.google_api_key:
        return False
    genai.configure(api_key=settings.google_api_key)
    return True


def identify_expert_persona(topic: str, source_snippet: str = "") -> str:
    """AGENT 0: The Router. Decides the best expert persona for the topic."""
    if not _configure():
        return "Expert Tutor"

    model = genai.GenerativeModel(MODEL_NAME)

    prompt = f"""
    Determine the single best "Job Title" or "Expert Persona" to teach the following topic.
    TOPIC: "{topic}"
    CONTEXT_SNIPPET: "{source_snippet[:200]}"

    Examples:
    - Topic: "SQL" -> "Senior Database Administrator"
    - Topic: "Monet" -> "Art History Professor"
    - Topic: "Tort Law" -> "Bar Exam Prep Tutor"

    OUTPUT: Just the Job Title. No extra text.
    """
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.warning("Persona identification failed: %s", e)
        return "Expert Tutor"


def analyze_knowledge_gaps(
    topic: str,
    existing_cards_text: str,
    source_text: str | None = None,
    num: int = 3,
) -> tuple[str, str]:
    """AGENT 1: The Curriculum Designer. Returns (gap_analysis, persona)."""
    if not _configure():
        return "Error: No API Key", "Expert"

    model = genai.GenerativeModel(MODEL_NAME)

    snippet = source_text[:500] if source_text else topic
    persona = identify_expert_persona(topic, snippet)

    if source_text:
        prompt = f"""
        You are a strict {persona}.

        SOURCE MATERIAL (The user's study document):
        '''
        {source_text[:30000]}
        '''

        USER'S EXISTING CARDS:
        '''
        {existing_cards_text}
        '''

        TASK: Compare the SOURCE MATERIAL vs EXISTING CARDS.
        Identify {num} concepts or specific examples found in the SOURCE MATERIAL that are missing from the existing cards.

        RULES:
        1. Act exactly like a {persona}.
        2. ONLY suggest concepts actually present in the SOURCE MATERIAL.
        3. Ignore outside knowledge not in the text.

        OUTPUT FORMAT:
        Bulleted list of missing concepts.
        """
    else:
        prompt = f"""
        You are a strict {persona}.

        USER GOAL: Expand knowledge on "{topic}".

        THE USER ALREADY KNOWS:
        '''
        {existing_cards_text}
        '''

        TASK: Identify {num} SPECIFIC "Knowledge Gaps" or new examples (e.g. Artworks) missing from the user's knowledge.

        CRITICAL RULES:
        1. Act exactly like a {persona}.
        2. Suggest advanced angles, edge cases, or comparisons specific to your field.
        3. Do NOT repeat what the user already knows.

        OUTPUT FORMAT:
        Bulleted list of missing concepts.
        """

    try:
        response = model.generate_content(prompt)
        return response.text.strip(), persona
    except Exception as e:
        return f"Error analyzing gaps: {e}", "Expert"


def generate_cards(
    missing_concepts: str,
    num: int,
    field_config: dict[str, str],
    persona: str = "Expert Tutor",
) -> str:
    """AGENT 2: The Content Creator. Returns raw pipe-separated card text."""
    if not _configure():
        return "Error: No API Key"

    fields_list = list(field_config.keys())
    structure_example = "|".join(f"{f}" for f in fields_list)

    instructions = []
    for f, f_type in field_config.items():
        if "topic" in f.lower():
            instructions.append(f"- Field '{f}': specific sub-topic (e.g. 'Impressionism: Light').")
        if f_type == "Image":
            instructions.append(f"- Field '{f}': 2-3 word search query. NO URLs.")
        elif f_type == "Audio":
            instructions.append(f"- Field '{f}': Text to be spoken.")
        elif f_type == "Code":
            instructions.append(f"- Field '{f}': <pre><code> wrapped.")
        elif f_type == "(Skip)":
            instructions.append(f"- Field '{f}': LEAVE EMPTY.")
        elif "topic" not in f.lower():
            instructions.append(f"- Field '{f}': Plain text (NO brackets).")

    prompt = f"""
    You are a strict {persona}.

    TASK: Generate {num} Anki cards based on these MISSING CONCEPTS:
    '''
    {missing_concepts}
    '''

    STRICT FORMAT:
    {structure_example}

    (Provide exactly ONE line per card, for {num} total cards.)

    INSTRUCTIONS:
    1. Output raw lines ONLY.
    2. Use exactly {len(fields_list)-1} pipes "|" per line.
    3. Do NOT use markdown bolding or brackets [ ] around text.
    4. {" ".join(instructions)}
    5. Write as a {persona} would (use correct terminology).
    6. CRITICAL: For the 'Artist' field, you MUST provide the FULL first and last name of the artist (e.g., 'Vincent van Gogh', not just 'van Gogh').
    7. CRITICAL: DO NOT use the pipe character "|" inside any of your text fields. It must ONLY be used to separate fields.

    Output only the raw text lines.
    """

    model = genai.GenerativeModel(MODEL_NAME)
    try:
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Error: {e}"
