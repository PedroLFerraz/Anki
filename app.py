import streamlit as st
import pandas as pd
# 
from backend import anki, agents, rag, media, utils

st.set_page_config(page_title="Agentic Anki", layout="wide", page_icon="🤖")

# --- POPUP ---
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

# --- MAIN ---
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
    
    col_sync, col_reset = st.columns([2,1])
    with col_sync:
        if st.button("🔄 Sync DB", help="Read cards from Anki"):
            notes = anki.get_all_notes_in_deck(sel_deck)
            n = rag.save_notes_to_db(notes)
            st.success(f"Synced {n} cards.")
    
    with col_reset:
        if st.button("🗑️", help="Force Reset Database"):
            import os
            try:
                os.remove("anki_notes.pkl")
                os.remove("anki_matrix.pkl")
                os.remove("anki_vectorizer.pkl")
                st.toast("Database Cleared", icon="🗑️")
            except: pass

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
        field_types[f] = st.selectbox(f"{f}", ["Text", "Image", "Code", "Audio", "(Skip)"], index=default)

# --- WORKFLOW ---
col1, col2 = st.columns([4, 6])

with col1:
    st.subheader("1. Agent Workflow")
    topic = st.text_input("Topic", "Impressionism")
    num = st.slider("Count", 1, 10, 3)
    
    if st.button("🚀 Run Agents"):
        # 1. Research
        with st.status("🕵️ Researching...", expanded=True) as status:
            source = agents.research_topic(topic)
            if source != topic:
                status.write("Topic expanded into Guide.")
                with st.expander("View Guide"): st.write(source)
            status.update(label="Research Done", state="complete", expanded=False)
        
        # 2. Generation
        with st.spinner("🃏 Generating Cards..."):
            # IMPROVED CONTEXT LOGIC
            # Query 1: Exact topic (e.g., "Degas")
            ctx_1 = rag.query_context(topic) 
            # Query 2: The expanded guide (e.g., "Degas ballerinas...")
            ctx_2 = rag.query_context(source[:200])
            
            # Merge and Dedup
            combined_ctx = list(set(ctx_1 + ctx_2))
            context_str = "\n".join(combined_ctx) if combined_ctx else "No context found (Starting fresh)."
            
            # DEBUG: Prove to user what AI sees
            with st.expander(f"🧠 AI Memory ({len(combined_ctx)} existing cards found)"):
                st.info("The AI has been told NOT to generate these cards:")
                st.text(context_str[:1500])
            
            raw = agents.generate_cards(source, context_str, num, field_types)
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
                    if ftype == "(Skip)" or not val or len(val) < 2: 
                        note_fields[f] = ""
                        continue
                    
                    if ftype == "Image" and "img src" not in val:
                        status.info(f"🖼️ Searching: '{val}'")
                        candidates = media.search_images(val)
                        if candidates:
                            fname = media.download_image_candidates(candidates)
                            if fname: note_fields[f] = f'<img src="{fname}">'
                            else: st.warning(f"Download failed: {val}")
                        else: st.warning(f"No images: {val}")

                    elif ftype == "Audio" and "[sound" not in val:
                        status.info(f"🔊 Generating Audio...")
                        fname = media.generate_audio(val, audio_lang)
                        if fname: note_fields[f] = f'[sound:{fname}]'

                anki.add_note(sel_deck, sel_model, note_fields)
                bar.progress((idx+1)/len(to_add))
            
            status.success("Done!")
            st.balloons()