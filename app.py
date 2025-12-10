import streamlit as st
import google.generativeai as genai
import requests
import json
import base64
import pandas as pd
import chromadb
import os
import re
import tempfile
from gtts import gTTS

# --- Configuration ---
ANKI_CONNECT_URL = "http://localhost:8765"
DB_PATH = "./anki_vector_store"
# As explicitly requested
MODEL_NAME = "gemini-2.5-flash-lite"

def get_secret(key):
    if key in st.secrets:
        return st.secrets[key]
    return None

# --- Security Check ---
if not get_secret("GOOGLE_API_KEY"):
    st.error("🚨 CRITICAL: Google API Key not found in secrets.")
    st.info("Please create `.streamlit/secrets.toml` and add `GOOGLE_API_KEY`.")
    st.stop()

# --- AnkiConnect ---
def anki_invoke(action, **params):
    try:
        payload = json.dumps({"action": action, "version": 6, "params": params})
        response = requests.post(ANKI_CONNECT_URL, data=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def get_model_fields(model_name):
    res = anki_invoke("modelFieldNames", modelName=model_name)
    return res.get("result", [])

def store_media(filename, data_b64):
    """Generic function to store any media (Image or Audio) in Anki."""
    res = anki_invoke("storeMediaFile", filename=filename, data=data_b64)
    if not res.get("error"):
        return filename
    return None

# --- MEDIA HANDLERS (Image & Audio) ---

def download_image(url):
    """Downloads image disguised as a browser."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        filename = f"gemini_img_{abs(hash(url))}.jpg"
        b64_data = base64.b64encode(response.content).decode('utf-8')
        return store_media(filename, b64_data)
    except Exception as e:
        st.write(f"⚠️ Image Error {url}: {e}")
        return None

def generate_audio(text, lang='en'):
    """Generates MP3 from text using gTTS."""
    try:
        # Create temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
            tts = gTTS(text=text, lang=lang)
            tts.save(fp.name)
            temp_path = fp.name
        
        # Read and encode
        with open(temp_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode('utf-8')
        
        # Cleanup
        os.remove(temp_path)
        
        # Store in Anki
        # Sanitize filename (take first 10 chars of text)
        safe_name = re.sub(r'[^a-zA-Z0-9]', '', text[:10])
        filename = f"gemini_audio_{safe_name}_{abs(hash(text))}.mp3"
        return store_media(filename, b64_data)
    except Exception as e:
        st.write(f"⚠️ Audio Error: {e}")
        return None

def search_google_image(query):
    api_key = get_secret("GOOGLE_API_KEY")
    cx = get_secret("GOOGLE_SEARCH_CX")
    if not api_key or not cx: return None
    
    url = "https://www.googleapis.com/customsearch/v1"
    params = {"q": query, "cx": cx, "key": api_key, "searchType": "image", "num": 1, "safe": "active"}
    try:
        res = requests.get(url, params=params)
        data = res.json()
        if "items" in data: return data["items"][0]["link"]
    except: pass
    return None

# --- RAG Logic ---
def get_chroma_client():
    return chromadb.PersistentClient(path=DB_PATH)

def sync_deck_to_db(deck_name):
    st.toast(f"Syncing {deck_name}...", icon="⏳")
    find_res = anki_invoke("findNotes", query=f'deck:"{deck_name}"')
    note_ids = find_res.get("result", [])
    if not note_ids: return 0

    notes_data = []
    chunk_size = 50
    for i in range(0, len(note_ids), chunk_size):
        chunk = note_ids[i:i+chunk_size]
        info_res = anki_invoke("notesInfo", notes=chunk)
        if info_res.get("result"):
            notes_data.extend(info_res["result"])

    documents = []
    ids = []
    metadatas = []
    for note in notes_data:
        fields = note["fields"]
        content = " | ".join([v["value"] for v in fields.values()])
        documents.append(content)
        ids.append(str(note["noteId"]))
        metadatas.append({"deck": deck_name})

    client = get_chroma_client()
    try: client.delete_collection(name="anki_cards")
    except: pass
    collection = client.create_collection(name="anki_cards")
    
    batch_size = 100
    for i in range(0, len(documents), batch_size):
        collection.add(documents=documents[i:i+batch_size], ids=ids[i:i+batch_size], metadatas=metadatas[i:i+batch_size])
    return len(documents)

def query_vector_db(topic, n_results=15):
    client = get_chroma_client()
    try:
        collection = client.get_collection(name="anki_cards")
        results = collection.query(query_texts=[topic], n_results=n_results)
        return results['documents'][0] 
    except: return []

# --- AI Logic ---

def generate_dynamic_cards(topic, num, field_config):
    """
    field_config is a dict: {'Front': 'Text', 'Image': 'Image', 'Sound': 'Audio'}
    """
    api_key = get_secret("GOOGLE_API_KEY")
    relevant_cards = query_vector_db(topic)
    context_str = "\n".join(relevant_cards) if relevant_cards else "No existing cards."
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(MODEL_NAME)
    
    fields_list = list(field_config.keys())
    structure_str = "|".join(f"[{f}]" for f in fields_list)

    # Build instructions based on types
    type_instructions = []
    for f, f_type in field_config.items():
        if f_type == "Image":
            type_instructions.append(f"- Field '{f}': Provide a 2-3 word Google Search query (e.g. 'Vermeer Girl with Pearl Earring'). Do NOT provide a URL.")
        elif f_type == "Audio":
            type_instructions.append(f"- Field '{f}': Provide the text that should be spoken (e.g. the German sentence).")
        elif f_type == "Code":
            type_instructions.append(f"- Field '{f}': Provide code wrapped in <pre><code> tags.")
        else:
            type_instructions.append(f"- Field '{f}': Plain text content.")

    prompt = f"""
    Generate {num} Anki cards on "{topic}".
    
    CONTEXT (My existing knowledge):
    '''
    {context_str}
    '''
    
    STRICT FORMAT:
    {structure_str}
    
    INSTRUCTIONS:
    1. Output raw lines ONLY.
    2. Use exactly {len(fields_list) - 1} pipes "|" per line.
    3. Do NOT use markdown code blocks.
    {"\n    ".join(type_instructions)}
    
    Output only the raw text lines.
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Error: {e}"

def smart_parse(raw_text, fields):
    parsed_cards = []
    clean_text = raw_text.replace("```markdown", "").replace("```text", "").replace("```", "").strip()
    lines = clean_text.split('\n')
    expected_count = len(fields)
    
    for line in lines:
        line = re.sub(r'^[\d\)\.\-\*]+\s*', '', line).strip()
        if not line or "|" not in line: continue 
            
        parts = [p.strip() for p in line.split('|')]
        
        if len(parts) == expected_count + 1 and parts[-1] == "": parts.pop()
        if len(parts) == expected_count - 1: parts.append("") 

        if len(parts) == expected_count:
            row = {fields[i]: parts[i] for i in range(expected_count)}
            row["✅"] = True 
            parsed_cards.append(row)
    return parsed_cards

# --- UI ---
st.set_page_config(page_title="Universal Anki Generator", layout="wide", page_icon="🎨")
st.title(f"🎨 Universal Anki Generator ({MODEL_NAME})")

if not anki_invoke("version").get("result"):
    st.error("❌ AnkiConnect is unreachable.")
    st.stop()

# --- SIDEBAR CONFIGURATION ---
with st.sidebar:
    st.header("1. Deck & Model")
    decks = anki_invoke("deckNames").get("result", [])
    models = anki_invoke("modelNames").get("result", [])
    
    selected_deck = st.selectbox("Deck", decks)
    selected_model = st.selectbox("Note Type", models)
    
    if st.button("🔄 Sync DB"):
        with st.spinner("Syncing..."):
            n = sync_deck_to_db(selected_deck)
            st.success(f"Synced {n} cards.")

    st.divider()
    st.header("2. Field Configuration")
    
    fields = get_model_fields(selected_model)
    field_types = {}
    
    # Global Audio Language
    audio_lang = st.selectbox("Audio Language", ["en", "de", "pt"], index=0, help="For Audio fields")

    # Dynamic Field Type Selectors with Smart Defaults
    for f in fields:
        # Smart Default Logic
        default_idx = 0 # Text
        f_lower = f.lower()
        if any(x in f_lower for x in ["image", "bild", "img", "pic"]): default_idx = 1
        elif any(x in f_lower for x in ["code", "snippet"]): default_idx = 2
        elif any(x in f_lower for x in ["audio", "sound", "ton", "pronunciation"]): default_idx = 3
        
        # UI
        field_types[f] = st.selectbox(
            f"Type: {f}", 
            ["Text", "Image", "Code", "Audio"], 
            index=default_idx,
            key=f"type_{f}"
        )

col1, col2 = st.columns([4, 6])

with col1:
    st.subheader("Generate Content")
    topic = st.text_input("Topic", "German C2 Vocabulary")
    num_cards = st.slider("Count", 1, 10, 3)
    
    if st.button("Generate"):
        with st.spinner("Dreaming up content..."):
            raw = generate_dynamic_cards(topic, num_cards, field_types)
            cards = smart_parse(raw, fields)
            
            if not cards:
                st.error("Generation failed. Raw Output:")
                st.code(raw)
            else:
                st.session_state['gen_cards'] = cards
                st.success(f"Generated {len(cards)} cards!")

with col2:
    st.subheader("Selection & Import")
    if 'gen_cards' in st.session_state:
        df = pd.DataFrame(st.session_state['gen_cards'])
        
        # UI Setup
        cols = ["✅"] + [c for c in df.columns if c != "✅"]
        df = df[cols]
        
        edited_df = st.data_editor(
            df,
            column_config={"✅": st.column_config.CheckboxColumn("Add?", default=True)},
            disabled=fields, 
            hide_index=True,
            use_container_width=True
        )
        
        selected_rows = edited_df[edited_df["✅"] == True]
        
        if st.button(f"🚀 Process & Add {len(selected_rows)} Cards"):
            bar = st.progress(0)
            status = st.empty()
            
            for idx, row in selected_rows.iterrows():
                note_fields = {k:v for k,v in row.to_dict().items() if k != "✅"}
                
                # --- PROCESS FIELD TYPES ---
                for f_name, f_value in note_fields.items():
                    f_type = field_types.get(f_name, "Text")
                    
                    if not f_value or len(f_value) < 2: continue

                    # 1. IMAGE Processing
                    if f_type == "Image" and "img src" not in f_value:
                        status.info(f"🖼️ Searching Image: {f_value}")
                        url = search_google_image(f_value)
                        if url:
                            fname = download_image(url)
                            if fname: note_fields[f_name] = f'<img src="{fname}">'

                    # 2. AUDIO Processing
                    elif f_type == "Audio" and "[sound" not in f_value:
                        status.info(f"🔊 Generating Audio ({audio_lang}): {f_value[:20]}...")
                        fname = generate_audio(f_value, lang=audio_lang)
                        if fname: note_fields[f_name] = f'[sound:{fname}]'
                
                # Add to Anki
                note = {
                    "deckName": selected_deck, 
                    "modelName": selected_model, 
                    "fields": note_fields, 
                    "options": {"allowDuplicate": False}
                }
                anki_invoke("addNote", note=note)
                bar.progress((idx+1)/len(selected_rows))
            
            status.success("Done! All media processed and uploaded.")
            st.balloons()