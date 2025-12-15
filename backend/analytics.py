import sqlite3
import pandas as pd
import json
from datetime import datetime

DB_NAME = "anki_analytics.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Updated: Added 'deck_name' column
    c.execute('''CREATE TABLE IF NOT EXISTS runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        topic TEXT,
        deck_name TEXT, 
        prompt_type TEXT,
        total_generated INTEGER
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS cards (
        card_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER,
        topic TEXT,
        front TEXT,
        back TEXT,
        fields_json TEXT,
        status TEXT,
        FOREIGN KEY(run_id) REFERENCES runs(run_id)
    )''')
    
    conn.commit()
    conn.close()

def log_generation_run(topic, deck_name, prompt_type, cards_data, accepted_indices):
    """
    Logs generation data including the target DECK.
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Ensure column exists (Migration for existing users)
    try:
        c.execute("ALTER TABLE runs ADD COLUMN deck_name TEXT")
    except:
        pass # Column already exists
    
    # 1. Log the Run with Deck Name
    c.execute("INSERT INTO runs (topic, deck_name, prompt_type, total_generated) VALUES (?, ?, ?, ?)",
              (topic, deck_name, prompt_type, len(cards_data)))
    run_id = c.lastrowid
    
    # 2. Log each Card
    for i, card in enumerate(cards_data):
        status = "ACCEPTED" if i in accepted_indices else "REJECTED"
        
        keys = list(card.keys())
        clean_keys = [k for k in keys if k != '✅']
        front = card.get(clean_keys[0], "") if len(clean_keys) > 0 else ""
        back = card.get(clean_keys[1], "") if len(clean_keys) > 1 else ""
        
        c.execute('''INSERT INTO cards (run_id, topic, front, back, fields_json, status) 
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (run_id, topic, front, back, json.dumps(card), status))
        
    conn.commit()
    conn.close()

def get_analytics_df(deck_filter=None):
    """
    Returns data, optionally filtered by a specific deck.
    """
    conn = sqlite3.connect(DB_NAME)
    
    query = """
        SELECT 
            c.topic,
            r.deck_name,
            COUNT(*) as total_cards,
            SUM(CASE WHEN c.status='ACCEPTED' THEN 1 ELSE 0 END) as accepted,
            SUM(CASE WHEN c.status='REJECTED' THEN 1 ELSE 0 END) as rejected
        FROM cards c
        JOIN runs r ON c.run_id = r.run_id
    """
    
    params = []
    if deck_filter and deck_filter != "All Decks":
        query += " WHERE r.deck_name = ?"
        params.append(deck_filter)
        
    query += " GROUP BY c.topic, r.deck_name"
    
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def get_recent_logs(deck_filter=None):
    conn = sqlite3.connect(DB_NAME)
    
    query = """
        SELECT c.card_id, r.timestamp, r.deck_name, c.topic, c.front, c.status 
        FROM cards c
        JOIN runs r ON c.run_id = r.run_id
    """
    
    params = []
    if deck_filter and deck_filter != "All Decks":
        query += " WHERE r.deck_name = ?"
        params.append(deck_filter)
        
    query += " ORDER BY c.card_id DESC LIMIT 50"
    
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def get_unique_decks():
    """Get list of all decks ever used in the logs."""
    conn = sqlite3.connect(DB_NAME)
    try:
        df = pd.read_sql_query("SELECT DISTINCT deck_name FROM runs WHERE deck_name IS NOT NULL", conn)
        return ["All Decks"] + df['deck_name'].tolist()
    except:
        return ["All Decks"]
    finally:
        conn.close()

init_db()