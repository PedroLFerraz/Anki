import streamlit as st
import pandas as pd
from backend import anki, agents, rag, media, utils

st.set_page_config(page_title="Agentic Anki", layout="wide", page_icon="🤖")

# --- POPUP: NEW DECK WIZARD ---
@st.dialog("✨ Create New Learning Project")
def create_project_wizard():
    st.write("Let's set up a new space for your learning.")
    
    new_deck_name = st.text_input("Project Name (Deck)", placeholder="e.g., Art History 101")
    model_option = st.radio("Card Template", ["Create Optimized 'Agentic' Template", "Use Existing Anki Model"])
    
    existing_model = None
    if "Use Existing" in model_option:
        existing_model = st.selectbox("Select Model", anki.get_model_names())
    
    description = st.text_area("What is this deck about?", placeholder="Context helps the AI...")
    
    if st.button("🚀 Create Project"):
        if not new_deck_name:
            st.error("Please name your deck.")
        else:
            anki.create_deck(new_deck_name)
            final_model = existing_model
            if "Create Optimized" in model_option:
                final_model = "AI Agentic Note"
                anki.create_custom_model(final_model, description)
            
            st.success(f"Created '{new_deck_name}'!")
            st.session_state['wiz_deck'] = new_deck_name
            st.session_state['wiz_model'] = final_model
            st.rerun()

# --- MAIN APP ---
st.title("🤖 Agentic Anki Generator")

if not anki.invoke("version").get("result"):
    st.error("❌ AnkiConnect is unreachable. Open Anki first.")
    st.stop()

# --- SIDEBAR ---
with st.sidebar:
    st.header("Project Settings")
    
    if st.button("➕ New Project Wizard", type="primary"):
        create_project_wizard()
        
    decks = anki.get_deck_names()
    models = anki.get_model_names()
    
    d_idx = decks.index(st.session_state.get('wiz_deck')) if st.session_state.get('wiz_deck') in decks else 0
    m_idx = models.index(st.session_state.get('wiz_model')) if st.session_state.get('wiz_model') in models else 0
    
    sel_deck = st.selectbox("Active Deck", decks, index=d_idx)
    sel_model = st.selectbox("Note Type", models, index=m_idx)
    
    if st.button("🔄 Sync RAG DB"):
        notes = anki.get_all_notes_in_deck(sel_deck)
        n = rag.save_notes_to_db(notes)
        st.success(f"Synced {n} cards.")

    with st.expander("🛠️ Debug Image Search"):
        test_q = st.text_input("Test Query", "Van Gogh Starry Night")
        if st.button("Test Search"):
            # UPDATED: Returns a list now
            urls = media.search_images(test_q)
            if urls:
                st.success(f"Found {len(urls)} candidates.")
                # Try downloading the first one just to show it works
                fname = media.download_image_candidates(urls)
                if fname:
                    st.write("✅ Download & Embed successful!")
                else:
                    st.error("❌ All candidates blocked.")
            else:
                st.error("Search failed. No results.")

    st.divider()
    st.subheader("Field Mapping")
    fields = anki.get_model_fields(sel_model)
    field_types = {}
    audio_lang = st.selectbox("Audio Lang", ["en", "de", "fr", "es", "ja"], index=0)

    for f in fields:
        default = 0
        if any(x in f.lower() for x in ["img", "bild", "image", "context"]): default = 1
        elif "code" in f.lower(): default = 2
        elif "audio" in f.lower(): default = 3
        field_types[f] = st.selectbox(f"{f}", ["Text", "Image", "Code", "Audio"], index=default)

# --- WORKFLOW ---
col1, col2 = st.columns([4, 6])

with col1:
    st.subheader("1. Agent Workflow")
    topic = st.text_input("Topic", "Impressionism")
    num = st.slider("Count", 1, 10, 3)
    
    if st.button("🚀 Run Agents"):
        with st.status("🕵️ Researching...", expanded=True) as status:
            source = agents.research_topic(topic)
            if source != topic:
                status.write("Topic expanded into Guide.")
                with st.expander("View Guide"): st.write(source)
            status.update(label="Research Done", state="complete", expanded=False)
        
        with st.spinner("🃏 Generating Cards..."):
            ctx_list = rag.query_context(source[:100])
            ctx_str = "\n".join(ctx_list) if ctx_list else "No context."
            
            raw = agents.generate_cards(source, ctx_str, num, field_types)
            cards = utils.smart_parse(raw, fields)
            
            if cards:
                st.session_state['gen_cards'] = cards
                st.success(f"{len(cards)} cards ready!")
            else:
                st.error("Generation failed.")
                st.code(raw)

with col2:
    st.subheader("2. Review & Import")
    if 'gen_cards' in st.session_state:
        df = pd.DataFrame(st.session_state['gen_cards'])
        cols = ["✅"] + [c for c in df.columns if c != "✅"]
        edited_df = st.data_editor(
            df[cols],
            column_config={"✅": st.column_config.CheckboxColumn("Add?", default=True)},
            disabled=fields,
            hide_index=True,
            use_container_width=True
        )
        
        to_add = edited_df[edited_df["✅"] == True]
        
        if st.button(f"📥 Import {len(to_add)} Cards"):
            bar = st.progress(0)
            status = st.empty()
            
            for idx, row in to_add.iterrows():
                note_fields = {k:v for k,v in row.to_dict().items() if k != "✅"}
                
                for f, val in note_fields.items():
                    ftype = field_types.get(f, "Text")
                    if not val or len(val) < 2: continue
                    
                    # --- IMAGE LOGIC (UPDATED) ---
                    if ftype == "Image" and "img src" not in val:
                        status.info(f"🖼️ Searching: '{val}'")
                        
                        # 1. Get List of URLs
                        candidates = media.search_images(val)
                        
                        if candidates:
                            # 2. Try them one by one
                            fname = media.download_image_candidates(candidates)
                            if fname:
                                note_fields[f] = f'<img src="{fname}">'
                            else:
                                st.warning(f"All {len(candidates)} images failed to download.")
                        else:
                            st.warning(f"No results for: {val}")

                    # --- AUDIO LOGIC ---
                    elif ftype == "Audio" and "[sound" not in val:
                        status.info(f"🔊 Generating Audio...")
                        fname = media.generate_audio(val, audio_lang)
                        if fname: note_fields[f] = f'[sound:{fname}]'

                anki.add_note(sel_deck, sel_model, note_fields)
                bar.progress((idx+1)/len(to_add))
            
            status.success("Done!")
            st.balloons()