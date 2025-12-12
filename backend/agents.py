import google.generativeai as genai
from .utils import get_secret

MODEL_NAME = "gemini-2.5-flash-lite"

def configure_genai():
    api_key = get_secret("GOOGLE_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
    return api_key

def analyze_knowledge_gaps(topic, existing_cards_text):
    """
    AGENT 1: The Curriculum Designer.
    Instead of just researching, it looks at what the user HAS vs what they NEED.
    """
    api_key = configure_genai()
    if not api_key: return "Error: No API Key"
    
    model = genai.GenerativeModel(MODEL_NAME)
    
    prompt = f"""
    You are a strict Data Science & Learning Curriculum Expert.
    
    USER GOAL: Master the topic "{topic}".
    
    CURRENT KNOWLEDGE (User's Existing Flashcards):
    '''
    {existing_cards_text}
    '''
    
    TASK: Identify 3-5 SPECIFIC "Knowledge Gaps" or "Advanced Concepts" that are missing from the Current Knowledge.
    
    RULES:
    1. IGNORE basic definitions if they are already present (e.g., if user has "What is a List?", do NOT suggest it).
    2. Focus on "Level 2 & 3" knowledge:
       - COMPARING concepts (e.g., List vs Tuple performance).
       - SCENARIOS (e.g., When to use X over Y?).
       - EDGE CASES (e.g., What happens if...?).
       - IMPLEMENTATION details.
    3. If the user has NO existing cards, suggest the foundational concepts first.
    
    OUTPUT FORMAT:
    Return ONLY a bulleted list of the missing concepts to be turned into cards.
    Example:
    - Performance difference between LEFT JOIN and INNER JOIN on nulls.
    - How Window Functions handle ties in ranking (DENSE_RANK vs RANK).
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Focus on advanced concepts of {topic}."

def generate_cards(missing_concepts, num, field_config):
    """
    AGENT 2: The Content Creator.
    Generates cards based ONLY on the specific gaps found by Agent 1.
    """
    api_key = configure_genai()
    
    fields_list = list(field_config.keys())
    structure = "|".join(f"[{f}]" for f in fields_list)
    
    instructions = []
    for f, f_type in field_config.items():
        if f_type == "Image": instructions.append(f"- Field '{f}': 2-3 word search query. NO URLs.")
        elif f_type == "Audio": instructions.append(f"- Field '{f}': Text to be spoken.")
        elif f_type == "Code": instructions.append(f"- Field '{f}': <pre><code> wrapped.")
        elif f_type == "(Skip)": instructions.append(f"- Field '{f}': LEAVE EMPTY.")
        else: instructions.append(f"- Field '{f}': Text.")

    prompt = f"""
    Generate {num} high-quality Anki cards.
    
    SOURCE MATERIAL (These are the specific gaps to fill):
    '''
    {missing_concepts}
    '''
    
    STRICT FORMAT:
    {structure}
    
    INSTRUCTIONS:
    1. {len(fields_list)-1} pipes "|" per line.
    2. No markdown blocks.
    3. {" ".join(instructions)}
    4. Make the Questions specific (Scenario-based preferred).
    5. Ensure the Answer explains "Why" or "How", not just "What".
    
    Output only the raw text lines.
    """
    
    model = genai.GenerativeModel(MODEL_NAME)
    try:
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Error: {e}"