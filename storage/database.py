import sqlite3
from core.config import settings


def get_connection():
    return sqlite3.connect(settings.db_path)


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        topic TEXT,
        embedding BLOB,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'GENERATED',
        card_type TEXT DEFAULT 'basic',
        extra_fields TEXT
    )""")

    c.execute("CREATE INDEX IF NOT EXISTS idx_cards_status ON cards(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_cards_topic ON cards(topic)")

    # Migration: add new columns to existing databases
    c.execute("PRAGMA table_info(cards)")
    existing_cols = {row[1] for row in c.fetchall()}
    if "card_type" not in existing_cols:
        c.execute("ALTER TABLE cards ADD COLUMN card_type TEXT DEFAULT 'basic'")
    if "extra_fields" not in existing_cols:
        c.execute("ALTER TABLE cards ADD COLUMN extra_fields TEXT")

    conn.commit()
    conn.close()


init_db()
