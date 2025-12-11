# backend/anki.py
import requests
import json

ANKI_CONNECT_URL = "http://localhost:8765"

def invoke(action, **params):
    try:
        payload = json.dumps({"action": action, "version": 6, "params": params})
        response = requests.post(ANKI_CONNECT_URL, data=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# ... existing getters (get_deck_names, get_model_names, etc.) ...
def get_deck_names():
    res = invoke("deckNames")
    return res.get("result", [])

def get_model_names():
    res = invoke("modelNames")
    return res.get("result", [])

def get_model_fields(model_name):
    res = invoke("modelFieldNames", modelName=model_name)
    return res.get("result", [])

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
    # ... (Keep existing logic) ...
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

# --- CREATION LOGIC ---

def create_deck(deck_name):
    """Creates a new empty deck."""
    return invoke("createDeck", deck=deck_name)

def create_custom_model(model_name, description=""):
    """
    Creates the 'Universal' Note Type with 6 standard fields.
    """
    if model_name in get_model_names():
        return False # Already exists

    # Standard Universal Fields
    fields = ["Topic", "Question", "Answer", "Image Context", "Audio Clip", "Code Snippet", "Notes"]
    
    # CSS for nice formatting
    css = """.card {
        font-family: arial; font-size: 20px; text-align: center; color: black; background-color: white;
    }
    .code { text-align: left; background: #f4f4f4; padding: 10px; border-radius: 5px; font-family: monospace; font-size: 14px; }
    .topic { font-size: 12px; color: #888; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 1px;}
    .notes { font-size: 14px; color: #666; margin-top: 20px; font-style: italic; }
    img { max-width: 100%; border-radius: 8px; margin-top: 10px; }
    """
    
    # Front Template
    front = """
    <div class='topic'>{{Topic}}</div>
    <div style='font-weight: bold;'>{{Question}}</div>
    <br>
    <div>{{Image Context}}</div>
    """
    
    # Back Template
    back = """
    {{FrontSide}}
    <hr id=answer>
    <div>{{Answer}}</div>
    <br>
    <div class='code'>{{Code Snippet}}</div>
    <br>
    <div>{{Audio Clip}}</div>
    <div class='notes'>{{Notes}}</div>
    """
    
    template = {
        "Name": "Universal Card",
        "Front": front,
        "Back": back
    }
    
    invoke("createModel", 
           modelName=model_name, 
           inOrderFields=fields, 
           css=css, 
           cardTemplates=[template])
    return True