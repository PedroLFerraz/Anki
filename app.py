import streamlit as st
import google.generativeai as genai
import requests
import json
import base64
import pandas as pd

# --- Configuration & Secrets ---
ANKI_CONNECT_URL = "http://localhost:8765"

def get_secret(key):
    """Safely get secret from streamlit secrets."""
    if key in st.secrets:
        return st.secrets[key]
    return None

# --- AnkiConnect Core ---

def anki_invoke(action, **params):
    try:
        payload = json.dumps({"action": action, "version": 6, "params": params})
        response = requests.post(ANKI_CONNECT_URL, data=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def get_model_fields(model_name):
    """Gets the list of field names for a specific Note Type."""
    res = anki_invoke("modelFieldNames", modelName=model_name)
    return res.get("result", [])

def store_image(url):
    """Downloads image from URL and uploads to Anki Media."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # Create unique filename
        filename = f"gemini_gen_{abs(hash(url))}.jpg"
        image_b64 = base64.b64encode(response.content).decode('utf-8')
        
        # Send to Anki
        res = anki_invoke("storeMediaFile", filename=filename, data=image_b64)
        if not res.get("error"):
            return filename
    except Exception as e:
        print(f"Image Error: {e}")
    return None

def search_google_image(query):
    """Uses Google Custom Search API via Secrets."""
    api_key = get_secret("GOOGLE_API_KEY")
    cx = get_secret("GOOGLE_SEARCH_CX")
    
    if not api_key or not cx:
        return None

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "q": query, "cx": cx, "key": api_key,
        "searchType": "image", "num": 1, "safe": "active"
    }
    
    try:
        res = requests.get(url, params=params)
        data = res.json()
        if "items" in data:
            return data["items"][0]["link"]
    except:
        pass
    return None

# --- AI Logic ---

def generate_dynamic_cards(topic, num, model_fields, image_target_field=None):
    """
    Generates cards based strictly on the Anki Model's structure.
    """
    api_key = get_secret("GOOGLE_API_KEY")
    if not api_key:
        return "Error: Missing GOOGLE_API_KEY in secrets.toml"

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash-lite")

    # Create a dynamic format string based on actual fields
    # e.g., "Front|Back|Context"
    structure_str = "|".join(f"[{f}]" for f in model_fields)
    
    # Specific instruction for the image field if it exists
    img_instruction = ""
    if image_target_field:
        img_instruction = f"For the '{image_target_field}' field, provide a short 2-3 word search query for an image (e.g., 'SQL Inner Join Diagram'). Do NOT provide an URL."

    prompt = f"""
    Generate {num} Anki flashcards on the topic: "{topic}".
    
    STRICT OUTPUT FORMAT:
    {structure_str}
    
    There are exactly {len(model_fields)} fields. Use exactly {len(model_fields) - 1} pipes "|" per line.
    
    INSTRUCTIONS:
    1. No "Q:" or "A:" prefixes.
    2. Code examples must be wrapped in <pre><code>...</code></pre> tags.
    3. Use <br> for line breaks inside code/text.
    4. {img_instruction}
    5. Prioritize Scenario-based questions for this topic.
    6. Build upon basic concepts to create harder cards.
    
    Output only the raw text lines.
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Error: {e}"

# --- Main App ---

st.set_page_config(page_title="Universal Anki Generator", layout="wide")
st.title("Universal Anki Generator")

# Check Connection
if not anki_invoke("version").get("result"):
    st.error("❌ AnkiConnect is unreachable. Is Anki open?")
    st.stop()

# Sidebar: Selection
with st.sidebar:
    st.header("Target")
    decks = anki_invoke("deckNames").get("result", [])
    models = anki_invoke("modelNames").get("result", [])
    
    selected_deck = st.selectbox("Deck", decks)
    selected_model = st.selectbox("Note Type", models)
    
    # DYNAMIC: Fetch fields for the selected model
    fields = get_model_fields(selected_model)
    st.write(f"Detected Fields: `{', '.join(fields)}`")
    
    st.divider()
    st.subheader("Image Handling")
    # Let user pick which field is the "Image Query" field
    image_field = st.selectbox("Which field needs an Image?", ["(None)"] + fields)

# Main Generation
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1. Define Content")
    topic = st.text_input("Topic", "SQL Window Functions")
    num_cards = st.slider("Quantity", 1, 10, 3)
    
    if st.button("Generate"):
        if not fields:
            st.error("No fields found for this Note Type.")
        else:
            with st.spinner("Generating..."):
                target_img_field = image_field if image_field != "(None)" else None
                raw = generate_dynamic_cards(topic, num_cards, fields, target_img_field)
                
                # Parse
                cards = []
                for line in raw.split('\n'):
                    parts = line.split('|')
                    # Flexible parsing: Try to match parts to fields
                    if len(parts) == len(fields):
                        row = {fields[i]: parts[i].strip() for i in range(len(fields))}
                        cards.append(row)
                
                if not cards:
                    st.error("Generation failed or format mismatch. Check raw output.")
                    st.code(raw)
                else:
                    st.session_state['gen_cards'] = cards
                    st.success(f"Generated {len(cards)} cards matching '{selected_model}' structure.")

with col2:
    st.subheader("2. Review & Push")
    if 'gen_cards' in st.session_state:
        df = pd.DataFrame(st.session_state['gen_cards'])
        edited_df = st.data_editor(df, num_rows="dynamic")
        
        if st.button("Add to Anki"):
            bar = st.progress(0)
            
            for idx, row in edited_df.iterrows():
                # Prepare fields
                note_fields = row.to_dict()
                
                # HANDLE IMAGE: If an image field was selected, process it now
                if image_field != "(None)" and image_field in note_fields:
                    query = note_fields[image_field]
                    if query and len(query) > 2:
                        # Only search if there is text
                        with st.spinner(f"Finding image for: {query}"):
                            url = search_google_image(query)
                            if url:
                                fname = store_image(url)
                                if fname:
                                    # Replace the query text with the HTML image tag
                                    note_fields[image_field] = f'<img src="{fname}">'
                
                # Add Note
                note = {
                    "deckName": selected_deck,
                    "modelName": selected_model,
                    "fields": note_fields,
                    "options": {"allowDuplicate": False}
                }
                
                anki_invoke("addNote", note=note)
                bar.progress((idx+1)/len(edited_df))
                
            st.success("Done!")