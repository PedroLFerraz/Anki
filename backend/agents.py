import google.generativeai as genai
from .utils import get_secret

MODEL_NAME = "gemini-2.5-flash-lite"

def configure_genai():
    api_key = get_secret("GOOGLE_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
    return api_key

def identify_expert_persona(topic, source_snippet=""):
    """
    AGENT 0: The Router.
    Decides who the best expert is for the given context.
    """
    api_key = configure_genai()
    if not api_key: return "Expert Tutor"
    
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
    except:
        return "Expert Tutor"

def analyze_knowledge_gaps(topic, existing_cards_text, source_text=None, num=3):
    """
    AGENT 1: The Curriculum Designer.
    Now dynamic based on the identified persona.
    """
    api_key = configure_genai()
    if not api_key: return "Error: No API Key", "Expert"
    
    model = genai.GenerativeModel(MODEL_NAME)
    
    # 1. Identify the Persona first
    snippet = source_text[:500] if source_text else topic
    persona = identify_expert_persona(topic, snippet)
    
    # 2. Build Prompt based on Source Mode
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
        # Return both the text AND the persona so we can pass it to Agent 2
        return response.text.strip(), persona
    except Exception as e:
        return f"Error analyzing gaps: {e}", "Expert"

def generate_cards(missing_concepts, num, field_config, persona="Expert Tutor"):
    """
    AGENT 2: The Content Creator.
    Uses the passed persona to maintain tone.
    """
    api_key = configure_genai()
    
    fields_list = list(field_config.keys())
    
    structure_example = "|".join(f"{f}" for f in fields_list)
    
    instructions = []
    for i, (f, f_type) in enumerate(field_config.items()):
        if "topic" in f.lower():
            instructions.append(f"- Field '{f}': specific sub-topic (e.g. 'Impressionism: Light').")
        
        if f_type == "Image": instructions.append(f"- Field '{f}': 2-3 word search query. NO URLs.")
        elif f_type == "Audio": instructions.append(f"- Field '{f}': Text to be spoken.")
        elif f_type == "Code": instructions.append(f"- Field '{f}': <pre><code> wrapped.")
        elif f_type == "(Skip)": instructions.append(f"- Field '{f}': LEAVE EMPTY.")
        elif "topic" not in f.lower(): instructions.append(f"- Field '{f}': Plain text (NO brackets).")

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