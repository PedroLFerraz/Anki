import streamlit as st
import pandas as pd
from backend import anki, agents, rag, media, utils, analytics # <--- Import new module

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
        topic = st.text_input("Topic", "Impressionism")
        num = st.slider("Count", 1, 10, 3)
        
        if st.button("🚀 Run Agents"):
            ctx_list = rag.query_context(topic)
            context_str = "\n".join(ctx_list) if ctx_list else "No existing cards found."
            
            with st.status("🕵️ Analyzing Knowledge Gaps...", expanded=True) as status:
                missing_concepts = agents.analyze_knowledge_gaps(topic, context_str)
                status.write("Identified missing concepts:")
                st.info(missing_concepts)
                status.update(label="Gap Analysis Done", state="complete", expanded=False)
            
            with st.spinner("🃏 Generating Cards..."):
                raw = agents.generate_cards(missing_concepts, num, field_types)
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
    st.header("📊 AI Performance & Learning Stats")
    
    df_stats = analytics.get_analytics_df()
    
    if not df_stats.empty:
        # Calculate Acceptance Rate
        df_stats['acceptance_rate'] = (df_stats['accepted'] / df_stats['total_cards']) * 100
        
        # Metric Cards
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Cards Generated", df_stats['total_cards'].sum())
        m2.metric("Cards Accepted", df_stats['accepted'].sum())
        m3.metric("Global Quality Score", f"{df_stats['acceptance_rate'].mean():.1f}%")
        
        st.divider()
        
        # Charts
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Accepted vs Rejected by Topic")
            st.bar_chart(df_stats.set_index("topic")[['accepted', 'rejected']], stack=True)
            
        with c2:
            st.subheader("Quality Score (Acceptance %)")
            st.bar_chart(df_stats.set_index("topic")['acceptance_rate'], color="#4CAF50")
            
        st.divider()
        st.subheader("Recent Generation Logs")
        st.dataframe(analytics.get_recent_logs(), width=1000)
    else:
        st.info("No data yet. Generate and Import some cards to see stats!")