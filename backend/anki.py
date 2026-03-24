import requests
import json
import streamlit as st # Need this for caching

ANKI_CONNECT_URL = "http://localhost:8765"

def invoke(action, **params):
    try:
        payload = json.dumps({"action": action, "version": 6, "params": params})
        response = requests.post(ANKI_CONNECT_URL, data=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# --- CACHED FUNCTIONS (The Fix) ---
# ttl=60 means "Refresh this data every 60 seconds" so it doesn't get stale

@st.cache_data(ttl=60) 
def get_deck_names():
    res = invoke("deckNames")
    return res.get("result", [])

@st.cache_data(ttl=60)
def get_model_names():
    res = invoke("modelNames")
    return res.get("result", [])

@st.cache_data(ttl=60)
def get_model_fields(model_name):
    if not model_name: return []
    res = invoke("modelFieldNames", modelName=model_name)
    return res.get("result", [])

# --- NON-CACHED FUNCTIONS (Actions) ---
# (Keep these normal because they CHANGE things)

def add_note(deck, model, fields):
    note = {
        "deckName": deck,
        "modelName": model,
        "fields": fields,
        "options": {"allowDuplicate": False}
    }
    return invoke("addNote", note=note)

def store_media_file(filename, b64_data):
    res = invoke("storeMediaFile", filename=filename, data=b64_data)
    if not res.get("error"):
        return filename
    return None

def get_all_notes_in_deck(deck_name):
    # Don't cache this heavily, or you won't see new cards you just added
    find_res = invoke("findNotes", query=f'deck:"{deck_name}"')
    note_ids = find_res.get("result", [])
    if not note_ids: return []

    notes_data = []
    chunk_size = 50
    for i in range(0, len(note_ids), chunk_size):
        chunk = note_ids[i:i+chunk_size]
        info_res = invoke("notesInfo", notes=chunk)
        if info_res.get("result"):
            notes_data.extend(info_res["result"])
    
    formatted = []
    for note in notes_data:
        fields = note["fields"]
        content = " | ".join([v["value"] for v in fields.values()])
        formatted.append({"id": str(note["noteId"]), "content": content, "deck": deck_name})
    return formatted

def create_deck(deck_name):
    # clear cache so the new deck shows up immediately
    get_deck_names.clear() 
    return invoke("createDeck", deck=deck_name)

def create_custom_model(model_name, description=""):
    if model_name in get_model_names():
        return False

    fields = ["Topic", "Question", "Answer", "Image Context", "Audio Clip", "Code Snippet", "Notes"]
    
    css = """.card { font-family: arial; font-size: 20px; text-align: center; color: black; background-color: white; }
    .code { text-align: left; background: #f4f4f4; padding: 10px; border-radius: 5px; font-family: monospace; font-size: 14px; }
    .topic { font-size: 12px; color: #888; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 1px;}
    .notes { font-size: 14px; color: #666; margin-top: 20px; font-style: italic; }
    img { max-width: 100%; border-radius: 8px; margin-top: 10px; }
    """
    
    front = "<div class='topic'>{{Topic}}</div><div style='font-weight: bold;'>{{Question}}</div><br><div>{{Image Context}}</div>"
    back = "{{FrontSide}}<hr id=answer><div>{{Answer}}</div><br><div class='code'>{{Code Snippet}}</div><br><div>{{Audio Clip}}</div><div class='notes'>{{Notes}}</div>"
    
    template = {
        "Name": "Universal Card",
        "Front": front,
        "Back": back
    }
    
    # --- THE FIX IS HERE ---
    # We pass 'sortFieldIndex': 1 (This means the 2nd field, "Question", is used for duplicates)
    req_params = {
        "modelName": model_name,
        "inOrderFields": fields,
        "css": css,
        "cardTemplates": [template]
    }
    
    # AnkiConnect doesn't let us set 'sortFieldIndex' easily during creation in older versions.
    # So we create it, then we Update it.
    invoke("createModel", **req_params)
    
    # Force Question to be the sort field
    # Note: If this fails on your version, you might need to change it manually in Anki: 
    # Tools -> Manage Note Types -> [Select Model] -> Fields -> [Select Question] -> "Sort by this field"
    return True

def create_artwork_model(model_name):
    if model_name in get_model_names():
        return False

    fields = ["Artwork", "Artist", "Nationality", "Title", "Date", "Period/Movement", "Permanent Location", "Note"]
    
    css = """.card {
 font-family: times;
 font-size: 24px;
 text-align: center;
 color: yellow;
 background-color: black;
}

.card1 { background-color: #003366; }
.card2 { background-color: #336633; }
.card3 { background-color: #663333; }
"""
    
    front = "<div style='font-family: Times; font-size: 24px; color: white'> Artist?</div>\n{{Artwork}}"
    back = "{{Artwork}}\n\n<hr id='answer'>\n<div style='font-family: Times; font-size: 30px; color: yellow'>{{Artist}}</div>\n<div style='font-size: 16px; color: #99CCFF'>({{Nationality}})\n<br>\n</br>\n<div style='font-family: Times; font-size: 16px; color: #99CCFF'> \"{{Title}}\"\n<div style='font-family: Times; font-size: 14px; color: #99CCFF'> \n{{#Date}}<div style='font-family: Times; font-size: 12px; color: #99CCFF'>({{Date}})</div>{{/Date}}\n<br>\n{{Period/Movement}}\n<br>\n{{Permanent Location}}\n<br>\n<br>\n<div style='font-family: Times; font-size: 16px; color: white'>{{Note}}</div>"
    
    template = {
        "Name": "Artwork Layout",
        "Front": front,
        "Back": back
    }
    
    req_params = {
        "modelName": model_name,
        "inOrderFields": fields,
        "css": css,
        "cardTemplates": [template]
    }
    
    invoke("createModel", **req_params)
    return True