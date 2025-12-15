import streamlit as st
import pandas as pd
from backend import anki, agents, rag, media, utils, analytics, ingestion # <--- Added ingestion

st.set_page_config(page_title="Agentic Anki", layout="wide", page_icon="🤖")

# --- WIZARD (Kept same) ---
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

# --- TABS FOR DASHBOARD ---
tab_gen, tab_data = st.tabs(["⚡ Generator", "📊 Analytics Dashboard"])

# ==========================================
# TAB 1: GENERATOR (Your existing app)
# ==========================================
with tab_gen:
    # --- SIDEBAR MOVED HERE FOR CLEANLINESS ---
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
        
        # --- NEW: SOURCE SELECTOR ---
        source_mode = st.radio("Source Material", ["General AI Knowledge", "Upload File (PDF/Txt)"], horizontal=True)
        
        topic = "General Context" # Default
        file_text = None
        
        if source_mode == "Upload File (PDF/Txt)":
            uploaded_file = st.file_uploader("Upload Study Material", type=['pdf', 'txt', 'md'])
            if uploaded_file:
                with st.spinner("Reading file..."):
                    file_text = ingestion.extract_text_from_file(uploaded_file)
                    st.caption(f"Loaded {len(file_text)} characters.")
                    topic = uploaded_file.name # Set topic to filename for logging
        else:
            topic = st.text_input("Topic", "Impressionism")
        
        num = st.slider("Count", 1, 10, 3)
        
        if st.button("🚀 Run Agents"):
            # 1. RAG Retrieval
            query_text = topic if not file_text else file_text[:500]
            ctx_list = rag.query_context(query_text)
            context_str = "\n".join(ctx_list) if ctx_list else "No existing cards found."
            
            # 2. Agent 1: Gap Analysis (Now returns Persona too)
            with st.status("🕵️ Analyzing Context...", expanded=True) as status:
                missing_concepts, persona = agents.analyze_knowledge_gaps(topic, context_str, source_text=file_text)
                
                # Show the user the detected persona
                status.write(f"🤖 AI Persona Adopted: **{persona}**")
                status.write("Plan of Action:")
                st.info(missing_concepts)
                
                # Save for Agent 2
                st.session_state['current_persona'] = persona
                
                status.update(label="Analysis Done", state="complete", expanded=False)
            
            # 3. Agent 2: Generation
            with st.spinner(f"🃏 Generating Cards as {st.session_state.get('current_persona', 'Expert')}..."):
                # Pass the persona here!
                current_p = st.session_state.get('current_persona', 'Expert Tutor')
                
                raw = agents.generate_cards(missing_concepts, num, field_types, persona=current_p)
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
                width="stretch"
            )
            
            # Identify Accepted Cards
            accepted_indices = edited_df.index[edited_df["✅"] == True].tolist()
            to_add = edited_df.loc[accepted_indices]
            
            if st.button(f"📥 Import {len(to_add)} Cards"):
                # --- NEW: LOGGING TO DATABASE ---
                analytics.log_generation_run(
                    topic=topic,
                    deck_name=sel_deck,
                    prompt_type="Agentic Gap Analysis",
                    cards_data=st.session_state['gen_cards'],
                    accepted_indices=accepted_indices
                )
                # -------------------------------

                bar = st.progress(0)
                status_box = st.empty()
                success_count = 0
                
                for idx, row in to_add.iterrows():
                    note_fields = {k:v for k,v in row.to_dict().items() if k != "✅"}
                    
                    for f, val in note_fields.items():
                        ftype = field_types.get(f, "Text")
                        if ftype == "(Skip)" or not val or len(val) < 2: 
                            note_fields[f] = ""
                            continue
                        
                        if ftype == "Image" and "img src" not in val:
                            status_box.info(f"🖼️ Searching: '{val}'")
                            candidates = media.search_images(val)
                            if candidates:
                                fname = media.download_image_candidates(candidates)
                                if fname: note_fields[f] = f'<img src="{fname}">'
                        
                        elif ftype == "Audio" and "[sound" not in val:
                            status_box.info(f"🔊 Generating Audio...")
                            fname = media.generate_audio(val, audio_lang)
                            if fname: note_fields[f] = f'[sound:{fname}]'

                    res = anki.add_note(sel_deck, sel_model, note_fields)
                    if res.get("result"): success_count += 1
                    
                    bar.progress((list(to_add.index).index(idx) + 1) / len(to_add))
                
                status_box.empty()
                st.success(f"Added {success_count} cards! Analytics updated.")
                st.balloons()

# ==========================================
# TAB 2: ANALYTICS DASHBOARD
# ==========================================
with tab_data:
    col_head, col_filter = st.columns([3, 1])
    with col_head:
        st.header("📊 AI Performance & Learning Stats")
    
    # --- DECK FILTER ---
    with col_filter:
        available_decks = analytics.get_unique_decks()
        filter_deck = st.selectbox("Filter by Deck", available_decks)
    
    # Pass the filter to the data fetchers
    df_stats = analytics.get_analytics_df(deck_filter=filter_deck)
    
    if not df_stats.empty:
        df_stats['acceptance_rate'] = (df_stats['accepted'] / df_stats['total_cards']) * 100
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Cards", df_stats['total_cards'].sum())
        m2.metric("Cards Accepted", df_stats['accepted'].sum())
        m3.metric("Quality Score", f"{df_stats['acceptance_rate'].mean():.1f}%")
        
        st.divider()
        
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Accepted vs Rejected")
            # Show Deck Name in tooltip if 'All Decks' is selected
            if filter_deck == "All Decks":
                st.bar_chart(df_stats, x="deck_name", y=['accepted', 'rejected'], stack=True)
            else:
                st.bar_chart(df_stats.set_index("topic")[['accepted', 'rejected']], stack=True)
            
        with c2:
            st.subheader("Quality Score (Acceptance %)")
            st.bar_chart(df_stats.set_index("topic")['acceptance_rate'], color="#4CAF50")
            
        st.divider()
        st.subheader(f"Recent Logs ({filter_deck})")
        st.dataframe(analytics.get_recent_logs(deck_filter=filter_deck), width=1000)
    else:
        st.info(f"No data found for {filter_deck}. Generate cards to see stats!")