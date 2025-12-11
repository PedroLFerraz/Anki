import google.generativeai as genai
from .utils import get_secret

# REMOVED: from .rag import query_context (This breaks the circle!)

MODEL_NAME = "gemini-2.5-flash-lite"

def configure_genai():
    api_key = get_secret("GOOGLE_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
    return api_key

def research_topic(topic):
    api_key = configure_genai()
    if not api_key: return "Error: No API Key"
    
    model = genai.GenerativeModel(MODEL_NAME)
    prompt = f"""
    Analyze: "{topic}".
    1. If specific/clear, output "SUFFICIENT".
    2. If vague, write a 300-word structured study guide.
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        return topic if "SUFFICIENT" in text else text
    except Exception as e:
        return topic

def generate_cards(source_material, context_text, num, field_config):
    """
    Now accepts 'context_text' as an argument instead of querying DB itself.
    """
    api_key = configure_genai()
    
    fields_list = list(field_config.keys())
    structure = "|".join(f"[{f}]" for f in fields_list)
    
    instructions = []
    for f, f_type in field_config.items():
        if f_type == "Image": instructions.append(f"Field '{f}': 2-3 word search query. NO URLs.")
        elif f_type == "Audio": instructions.append(f"Field '{f}': Text to be spoken.")
        elif f_type == "Code": instructions.append(f"Field '{f}': <pre><code> wrapped.")
        else: instructions.append(f"Field '{f}': Text.")

    prompt = f"""
    Generate {num} cards.
    SOURCE: {source_material}
    CONTEXT (Existing Cards):
    {context_text}
    
    FORMAT: {structure}
    RULES:
    1. {len(fields_list)-1} pipes per line.
    2. No markdown blocks.
    3. {" ".join(instructions)}
    """
    
    model = genai.GenerativeModel(MODEL_NAME)
    try:
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Error: {e}"