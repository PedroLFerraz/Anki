# backend/agents.py
import google.generativeai as genai
from .utils import get_secret

MODEL_NAME = "gemini-2.5-flash-lite"

def configure_genai():
    api_key = get_secret("GOOGLE_API_KEY")
    if api_key: genai.configure(api_key=api_key)
    return api_key

def research_topic(topic):
    api_key = configure_genai()
    if not api_key: return "Error: No API Key"
    model = genai.GenerativeModel(MODEL_NAME)
    prompt = f"Analyze '{topic}'. If specific, output 'SUFFICIENT'. If broad, write a 300-word study guide."
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        return topic if "SUFFICIENT" in text else text
    except: return topic

def generate_cards(source_material, context_text, num, field_config):
    api_key = configure_genai()
    
    fields_list = list(field_config.keys())
    structure = "|".join(f"[{f}]" for f in fields_list)
    
    instructions = []
    for f, f_type in field_config.items():
        if f_type == "Image": instructions.append(f"Field '{f}': 2-3 word search query. NO URLs.")
        elif f_type == "Audio": instructions.append(f"Field '{f}': Text to be spoken.")
        elif f_type == "Code": instructions.append(f"Field '{f}': <pre><code> wrapped.")
        elif f_type == "(Skip)": instructions.append(f"Field '{f}': LEAVE EMPTY.")
        else: instructions.append(f"Field '{f}': Text.")

    # --- THE NEW AGGRESSIVE PROMPT ---
    prompt = f"""
    You are an expert Anki card generator.
    
    TASK: Generate {num} NEW flashcards based on the SOURCE MATERIAL below.
    
    CRITICAL RULE: DO NOT DUPLICATE EXISTING KNOWLEDGE.
    I have provided a list of "EXISTING CARDS" that I already have.
    - If a concept is present in "EXISTING CARDS", IGNORE IT completely.
    - If the Source Material talks about "Degas Dancers" and I already have a card about "Degas Dancers", do NOT make another one.
    - Instead, find a *different* angle (e.g., his sculpture, his materials, his eyesight) or a *harder* question about the same topic.
    
    SOURCE MATERIAL:
    '''
    {source_material}
    '''
    
    EXISTING CARDS (DO NOT REPEAT THESE CONCEPTS):
    '''
    {context_text}
    '''
    
    OUTPUT FORMAT:
    {structure}
    
    INSTRUCTIONS:
    1. {len(fields_list)-1} pipes "|" per line.
    2. No markdown.
    3. {" ".join(instructions)}
    """
    
    model = genai.GenerativeModel(MODEL_NAME)
    try:
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Error: {e}"