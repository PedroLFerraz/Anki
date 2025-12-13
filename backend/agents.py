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
    """
    api_key = configure_genai()
    if not api_key: return "Error: No API Key"
    
    model = genai.GenerativeModel(MODEL_NAME)
    
    prompt = f"""
    You are a strict Data Science & Learning Expert.
    
    USER GOAL: Expand knowledge on "{topic}".
    
    THE USER ALREADY KNOWS (Do NOT repeat these):
    '''
    {existing_cards_text}
    '''
    
    TASK: Identify 3-5 SPECIFIC "Knowledge Gaps" that are missing from the user's knowledge.
    
    CRITICAL RULES:
    1. If the user already has a card about a specific fact, DO NOT suggest it.
    2. Suggest a DIFFERENT angle or advanced edge cases.
    3. Focus on "Why", "How", and "Compare", not just "What".
    
    OUTPUT FORMAT:
    Return ONLY a bulleted list of the missing concepts.
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Focus on advanced concepts of {topic}."

def generate_cards(missing_concepts, num, field_config):
    """
    AGENT 2: The Content Creator.
    """
    api_key = configure_genai()
    
    fields_list = list(field_config.keys())
    
    # FIX 1: Removed square brackets from here so the AI doesn't copy them
    structure_example = "|".join(f"{f}" for f in fields_list)
    
    instructions = []
    for i, (f, f_type) in enumerate(field_config.items()):
        # FIX 2: Specific instruction for the Topic field (usually the first one)
        if i == 0:
            instructions.append(f"- Field '{f}': specific sub-topic (e.g. 'Impressionism: Light' NOT just 'Impressionism').")
        
        if f_type == "Image": instructions.append(f"- Field '{f}': 2-3 word search query. NO URLs.")
        elif f_type == "Audio": instructions.append(f"- Field '{f}': Text to be spoken.")
        elif f_type == "Code": instructions.append(f"- Field '{f}': <pre><code> wrapped.")
        elif f_type == "(Skip)": instructions.append(f"- Field '{f}': LEAVE EMPTY.")
        else: instructions.append(f"- Field '{f}': Plain text (NO brackets).")

    prompt = f"""
    Generate {num} Anki cards based on these MISSING CONCEPTS:
    '''
    {missing_concepts}
    '''
    
    STRICT FORMAT:
    {structure_example}
    
    INSTRUCTIONS:
    1. Output raw lines ONLY.
    2. Use exactly {len(fields_list)-1} pipes "|" per line.
    3. Do NOT use markdown bolding or brackets [ ] around text.
    4. {" ".join(instructions)}
    5. Ensure questions are specific and answers explain "Why".
    
    Output only the raw text lines.
    """
    
    model = genai.GenerativeModel(MODEL_NAME)
    try:
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Error: {e}"