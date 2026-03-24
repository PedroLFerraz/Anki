import sqlite3
import json
from core.config import settings

# Exact match of the real "Great Works of Art" deck from the user's .apkg
ARTWORK_DECK_TYPE = {
    "name": "artwork",
    "fields_schema": json.dumps([
        {"name": "Artwork", "type": "Image"},
        {"name": "Artist", "type": "Text"},
        {"name": "Title", "type": "Text"},
        {"name": "Subtitle/Alternate Titles", "type": "Text"},
        {"name": "Title in Original Language", "type": "Text"},
        {"name": "Date", "type": "Text"},
        {"name": "Period/Movement", "type": "Text"},
        {"name": "Medium", "type": "Text"},
        {"name": "Nationality", "type": "Text"},
        {"name": "Note", "type": "Text"},
        {"name": "Image Source", "type": "(Skip)"},
        {"name": "Image copyright information", "type": "(Skip)"},
        {"name": "Permanent Location", "type": "Text"},
        {"name": "Instructive Link(s)", "type": "(Skip)"},
        {"name": "Gallery/Museum Link(s)", "type": "(Skip)"},
    ]),
    "templates": json.dumps([
        {
            "name": "Artist?",
            "front": (
                "<div style='font-family: Times; font-size: 24px; color: white'> Artist?</div>\n"
                "{{Artwork}}"
            ),
            "back": (
                "{{Artwork}}\n\n"
                "<hr id='answer'>\n"
                "<div style='font-family: Times; font-size: 30px; color: yellow'>{{Artist}}</div>\n"
                "<div style='font-size: 16px; color: #99CCFF'>({{Nationality}})\n"
                "<br>\n</br>\n"
                "<div style='font-family: Times; font-size: 16px; color: #99CCFF'> \"{{Title}}\"\n"
                "<div style='font-family: Times; font-size: 14px; color: #99CCFF'> \n"
                "{{#Date}}<div style='font-family: Times; font-size: 12px; color: #99CCFF'>"
                "({{Date}})</div>{{/Date}}\n"
                "<br>\n{{Period/Movement}}\n<br>\n{{Permanent Location}}\n<br>\n<br>\n"
                "<div style='font-family: Times; font-size: 16px; color: white'>{{Note}}</div>"
            ),
        },
        {
            "name": "Title?",
            "front": (
                "<div style='font-family: Times; font-size: 24px; color: white'> Title?</div>\n"
                "{{Artwork}}"
            ),
            "back": (
                "{{Artwork}}\n\n"
                "<hr id='answer'>\n"
                "<div style='font-family: Times; font-size: 30px; color: yellow'>\"{{Title}}\"</div>\n"
                "<div style='font-family: Times; font-size: 20px; color: yellow'>({{Date}})</div>\n"
                "<div style='font-family: Times; font-size: 12px; color: yellow;'>"
                "{{Subtitle/Alternate Titles}}</div>\n"
                "<br>\n"
                "<div style='font-family: Times; font-size: 16px; color: #99CCFF'> {{Artist}}\n"
                "<div style='font-size: 16px; color: #99CCFF'>({{Nationality}})\n"
                "<br>\n<br>\n{{Period/Movement}}\n<br>\n{{Permanent Location}}\n<br>\n<br>\n"
                "<div style='font-family: Times; font-size: 16px; color: white'>{{Note}}</div>"
            ),
        },
    ]),
    "css": """.card {
 font-family: times;
 font-size: 24px;
 text-align: center;
 color: yellow;
background-color: black }

.card1 { background-color: #003366 }
.card2 { background-color: #336633 }
.card3 { background-color: #663333 }""",
}


def get_connection():
    return sqlite3.connect(settings.db_path)


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS deck_types (
        name TEXT PRIMARY KEY,
        fields_schema TEXT NOT NULL,
        templates TEXT NOT NULL,
        css TEXT NOT NULL,
        anki_model_id INTEGER,
        anki_deck_id INTEGER
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        deck_type TEXT NOT NULL,
        fields_json TEXT NOT NULL,
        image_filename TEXT,
        audio_filename TEXT,
        embedding BLOB,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        source_topic TEXT,
        run_id INTEGER,
        status TEXT DEFAULT 'GENERATED',
        FOREIGN KEY(run_id) REFERENCES runs(run_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        topic TEXT,
        deck_name TEXT,
        deck_type TEXT,
        persona TEXT,
        total_generated INTEGER,
        total_accepted INTEGER
    )""")

    c.execute("CREATE INDEX IF NOT EXISTS idx_cards_status ON cards(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_cards_deck_type ON cards(deck_type)")

    # Migration: add anki_model_id, anki_deck_id columns if missing
    c.execute("PRAGMA table_info(deck_types)")
    existing_cols = {row[1] for row in c.fetchall()}
    if "anki_model_id" not in existing_cols:
        c.execute("ALTER TABLE deck_types ADD COLUMN anki_model_id INTEGER")
    if "anki_deck_id" not in existing_cols:
        c.execute("ALTER TABLE deck_types ADD COLUMN anki_deck_id INTEGER")

    # Seed artwork deck type
    c.execute(
        "INSERT OR IGNORE INTO deck_types (name, fields_schema, templates, css) VALUES (?, ?, ?, ?)",
        (
            ARTWORK_DECK_TYPE["name"],
            ARTWORK_DECK_TYPE["fields_schema"],
            ARTWORK_DECK_TYPE["templates"],
            ARTWORK_DECK_TYPE["css"],
        ),
    )

    conn.commit()
    conn.close()


init_db()
