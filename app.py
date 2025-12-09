import streamlit as st
import google.generativeai as genai
import requests
import json
import base64
import pandas as pd
import chromadb
import os
import re

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

def store_image(url):
    """
    Downloads image with 'Fake Browser' headers to bypass 403 errors.
    """
    try:
        # 1. Masquerade as a real Chrome browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com/'
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # 2. Convert to Base64 for Anki
        filename = f"gemini_gen_{abs(hash(url))}.jpg"
        image_b64 = base64.b64encode(response.content).decode('utf-8')
        
        # 3. Upload to Anki
        res = anki_invoke("storeMediaFile", filename=filename, data=image_b64)
        if not res.get("error"):
            return filename
    except Exception as e:
        # Log the error to UI so you can see it
        st.write(f"⚠️ Image Download Error for {url}: {e}")
        return None

def search_google_image(query):
    api_key = get_secret("GOOGLE_API_KEY")
    cx = get_secret("GOOGLE_SEARCH_CX")
    if not api_key or not cx: 
        st.error("Missing GOOGLE_SEARCH_CX in secrets.toml")
        return None
    
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "q": query, 
        "cx": cx, 
        "key": api_key, 
        "searchType": "image", 
        "num": 1, 
        "safe": "active"
    }
    
    try:
        res = requests.get(url, params=params)
        data = res.json()
        
        if "error" in data:
            st.session_state['last_img_error'] = data['error']
            return None
            
        if "items" in data and len(data["items"]) > 0:
            return data["items"][0]["link"]
        else:
            st.session_state['last_img_error'] = f"No items found for '{query}'"
            return None
    except Exception as e:
        st.session_state['last_img_error'] = str(e)
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

def generate_dynamic_cards(topic, num, model_fields, image_target_field=None):
    api_key = get_secret("GOOGLE_API_KEY")
    relevant_cards = query_vector_db(topic)
    context_str = "\n".join(relevant_cards) if relevant_cards else "No existing cards."
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(MODEL_NAME)

    structure_str = "|".join(f"[{f}]" for f in model_fields)
    img_instruction = ""
    if image_target_field:
        img_instruction = f"For the field '{image_target_field}', provide ONLY a 2-3 word search query (e.g. 'SQL Venn Diagram'). Do NOT provide an URL."

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
    2. Do NOT use markdown code blocks.
    3. Do NOT number the cards (e.g. no "1. Question").
    4. Use exactly {len(model_fields) - 1} pipes "|" per line.
    5. Code: <pre><code>...</code></pre> with <br> for breaks.
    6. {img_instruction}
    
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
        # REGEX: Removes "1.", "1)", "-", "*" from start of line
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
st.set_page_config(page_title="RAG Anki Generator", layout="wide", page_icon="🧠")
st.title(f"🧠 RAG Anki Generator")

if not anki_invoke("version").get("result"):
    st.error("❌ AnkiConnect is unreachable.")
    st.stop()

with st.sidebar:
    st.header("Config")
    decks = anki_invoke("deckNames").get("result", [])
    models = anki_invoke("modelNames").get("result", [])
    
    selected_deck = st.selectbox("Deck", decks)
    selected_model = st.selectbox("Note Type", models)
    
    if st.button("🔄 Sync DB"):
        with st.spinner("Syncing..."):
            n = sync_deck_to_db(selected_deck)
            st.success(f"Synced {n} cards.")

    fields = get_model_fields(selected_model)
    image_field = st.selectbox("Image Field", ["(None)"] + fields)

col1, col2 = st.columns([4, 6])

with col1:
    st.subheader("Generate")
    topic = st.text_input("Topic", "SQL Window Functions")
    num_cards = st.slider("Count", 1, 10, 3)
    
    if st.button("Generate"):
        if not fields:
            st.error("No fields found.")
        else:
            with st.spinner("Generating..."):
                target_img = image_field if image_field != "(None)" else None
                raw = generate_dynamic_cards(topic, num_cards, fields, target_img)
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
        
        # UI: Checkbox first
        cols = ["✅"] + [c for c in df.columns if c != "✅"]
        df = df[cols]

        # UI: Lock all fields except the Checkbox
        edited_df = st.data_editor(
            df,
            column_config={
                "✅": st.column_config.CheckboxColumn("Add?", default=True)
            },
            disabled=fields, # Locks text columns
            hide_index=True,
            use_container_width=True
        )
        
        # Filter Logic
        selected_rows = edited_df[edited_df["✅"] == True]
        
        if st.button(f"🚀 Add {len(selected_rows)} Selected Cards"):
            bar = st.progress(0)
            status = st.empty()
            
            for idx, row in selected_rows.iterrows():
                note_fields = {k:v for k,v in row.to_dict().items() if k != "✅"}
                
                # Image Logic
                if image_field != "(None)" and image_field in note_fields:
                    q = note_fields[image_field]
                    if q and len(q) > 2 and "img src" not in q:
                        status.info(f"Downloading image for: '{q}'...")
                        url = search_google_image(q)
                        if url:
                            fname = store_image(url)
                            if fname:
                                note_fields[image_field] = f'<img src="{fname}">'
                        else:
                            status.warning(f"No image found for: {q}")
                
                note = {
                    "deckName": selected_deck, 
                    "modelName": selected_model, 
                    "fields": note_fields, 
                    "options": {"allowDuplicate": False}
                }
                anki_invoke("addNote", note=note)
                bar.progress((idx+1)/len(selected_rows))
            
            status.success("Done!")
            st.balloons()
            
            if 'last_img_error' in st.session_state:
                with st.expander("⚠️ Image Search Debug Log"):
                    st.write(st.session_state['last_img_error'])