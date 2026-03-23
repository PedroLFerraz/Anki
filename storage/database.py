import sqlite3
import json
from core.config import settings

ARTWORK_DECK_TYPE = {
    "name": "artwork",
    "fields_schema": json.dumps([
        {"name": "Artwork", "type": "Image"},
        {"name": "Artist", "type": "Text"},
        {"name": "Nationality", "type": "Text"},
        {"name": "Title", "type": "Text"},
        {"name": "Date", "type": "Text"},
        {"name": "Period/Movement", "type": "Text"},
        {"name": "Permanent Location", "type": "Text"},
        {"name": "Note", "type": "Text"},
    ]),
    "front_template": "<div style='font-family: Times; font-size: 24px; color: white'> Artist?</div>\n{{Artwork}}",
    "back_template": (
        "{{Artwork}}\n\n<hr id='answer'>\n"
        "<div style='font-family: Times; font-size: 30px; color: yellow'>{{Artist}}</div>\n"
        "<div style='font-size: 16px; color: #99CCFF'>({{Nationality}})\n<br>\n</br>\n"
        "<div style='font-family: Times; font-size: 16px; color: #99CCFF'> \"{{Title}}\"\n"
        "<div style='font-family: Times; font-size: 14px; color: #99CCFF'> \n"
        "{{#Date}}<div style='font-family: Times; font-size: 12px; color: #99CCFF'>({{Date}})</div>{{/Date}}\n"
        "<br>\n{{Period/Movement}}\n<br>\n{{Permanent Location}}\n<br>\n<br>\n"
        "<div style='font-family: Times; font-size: 16px; color: white'>{{Note}}</div>"
    ),
    "css": """.card {
 font-family: times;
 font-size: 24px;
 text-align: center;
 color: yellow;
 background-color: black;
}

.card1 { background-color: #003366; }
.card2 { background-color: #336633; }
.card3 { background-color: #663333; }
""",
}


def get_connection():
    return sqlite3.connect(settings.db_path)


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS deck_types (
        name TEXT PRIMARY KEY,
        fields_schema TEXT NOT NULL,
        front_template TEXT NOT NULL,
        back_template TEXT NOT NULL,
        css TEXT NOT NULL
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

    # Seed artwork deck type
    c.execute(
        "INSERT OR IGNORE INTO deck_types (name, fields_schema, front_template, back_template, css) VALUES (?, ?, ?, ?, ?)",
        (
            ARTWORK_DECK_TYPE["name"],
            ARTWORK_DECK_TYPE["fields_schema"],
            ARTWORK_DECK_TYPE["front_template"],
            ARTWORK_DECK_TYPE["back_template"],
            ARTWORK_DECK_TYPE["css"],
        ),
    )

    conn.commit()
    conn.close()


init_db()
