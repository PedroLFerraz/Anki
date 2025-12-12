# 🤖 Agentic Anki Generator

A powerful, local AI tool that turns any topic into high-quality Anki flashcards. It uses an **Agentic Workflow** to research topics, check your existing deck for duplicates (RAG), and automatically format cards with images and audio.

<!-- ![App Screenshot](https://via.placeholder.com/800x400?text=Agentic+Anki+Dashboard+Preview) *(Replace with actual screenshot if you have one)* -->

## 🚀 Key Features

* **🕵️ Agentic Research:** If you type a broad topic (e.g., "Impressionism"), Agent 1 expands it into a detailed study guide before Agent 2 generates cards.
* **🧠 Smart RAG (No Duplicates):** Uses a local TF-IDF database to "read" your existing Anki deck. If you already have a card about "Degas", the AI won't generate it again.
* **🖼️ Auto-Images:** Searches **DuckDuckGo** and **Wikimedia Commons** for images (Art, Diagrams, Screenshots). No Google API keys required.
* **🔊 Auto-Audio:** Generates Text-to-Speech (MP3) for language cards automatically using `gTTS`.
* **⚡ Zero-Config Database:** No complex Vector DB installation. Uses `scikit-learn` for instant, lightweight text retrieval.
* **🛡️ "Select-Only" Workflow:** You review every card before it touches your Anki deck.

## 🛠️ Prerequisites

1.  **Anki** (Desktop App) must be installed and running.
2.  **AnkiConnect** (Add-on) must be installed.
    * *Code:* `2055492159`
    * *Config:* Ensure `"webBindAddress": "localhost"` or `"0.0.0.0"` in the add-on config.
3.  **Python 3.10+**

## 📦 Installation

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/yourusername/anki-agent.git](https://github.com/yourusername/anki-agent.git)
    cd anki-agent
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *(Note: If on Windows, `pysqlite3-binary` is handled automatically by the app code).*

3.  **Set up API Keys:**
    Create a file named `.streamlit/secrets.toml`:
    ```toml
    # Only Gemini API is needed now!
    GOOGLE_API_KEY = "AIzaSy..."
    ```

## ▶️ Usage

1.  Open Anki.
2.  Run the application:
    ```bash
    streamlit run app.py
    ```
3.  **First Time Setup:**
    * Click **"⚡ Create Default Deck & Model"** in the sidebar.
    * This creates a clean "AI Gen Deck" and a "Universal" Note Type ready for images/audio.
4.  **Workflow:**
    * **Topic:** Type a subject (e.g., "SQL Window Functions").
    * **Sync:** Click "🔄 Sync RAG DB" to let the AI learn your current cards.
    * **Generate:** Click "Run Agents".
    * **Review:** Select the cards you like and click "Import".

## 📂 Project Structure

```text
anki-agent/
├── app.py                 # Main Streamlit Interface (The "Frontend")
├── .streamlit/
│   └── secrets.toml       # API Keys
├── backend/               # Modular Logic
│   ├── agents.py          # Gemini AI (Researcher & Generator)
│   ├── anki.py            # AnkiConnect communication
│   ├── media.py           # DuckDuckGo/Wiki Search & Audio Gen
│   ├── rag.py             # TF-IDF Retrieval System
│   └── utils.py           # Text Parsing & Helpers
└── requirements.txt       # Python Dependencies