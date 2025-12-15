import sqlite3
import pandas as pd
import json
from datetime import datetime

DB_NAME = "anki_analytics.db"

def init_db():
    """Creates the tables if they don't exist."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Table 1: Runs (Each time you click 'Generate')
    c.execute('''CREATE TABLE IF NOT EXISTS runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        topic TEXT,
        prompt_type TEXT,
        total_generated INTEGER
    )''')
    
    # Table 2: Cards (Individual cards and whether you liked them)
    c.execute('''CREATE TABLE IF NOT EXISTS cards (
        card_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER,
        topic TEXT,
        front TEXT,
        back TEXT,
        fields_json TEXT,
        status TEXT, -- 'ACCEPTED' or 'REJECTED'
        FOREIGN KEY(run_id) REFERENCES runs(run_id)
    )''')
    
    conn.commit()
    conn.close()

def log_generation_run(topic, prompt_type, cards_data, accepted_indices):
    """
    Logs a batch of cards.
    cards_data: List of dicts (all cards generated)
    accepted_indices: List of integers (indexes of cards the user checked)
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # 1. Log the Run
    c.execute("INSERT INTO runs (topic, prompt_type, total_generated) VALUES (?, ?, ?)",
              (topic, prompt_type, len(cards_data)))
    run_id = c.lastrowid
    
    # 2. Log each Card
    for i, card in enumerate(cards_data):
        status = "ACCEPTED" if i in accepted_indices else "REJECTED"
        
        # We try to guess Front/Back for analytics, or just dump JSON
        # Assuming first field is Topic/Front and second is Question/Back
        keys = list(card.keys())
        # Filter out the checkbox key if present
        clean_keys = [k for k in keys if k != '✅']
        
        front = card.get(clean_keys[0], "") if len(clean_keys) > 0 else ""
        back = card.get(clean_keys[1], "") if len(clean_keys) > 1 else ""
        
        c.execute('''INSERT INTO cards (run_id, topic, front, back, fields_json, status) 
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (run_id, topic, front, back, json.dumps(card), status))
        
    conn.commit()
    conn.close()

def get_analytics_df():
    """Returns raw data for the dashboard."""
    conn = sqlite3.connect(DB_NAME)
    
    # Query: Acceptance Rate per Topic
    df = pd.read_sql_query("""
        SELECT 
            topic,
            COUNT(*) as total_cards,
            SUM(CASE WHEN status='ACCEPTED' THEN 1 ELSE 0 END) as accepted,
            SUM(CASE WHEN status='REJECTED' THEN 1 ELSE 0 END) as rejected
        FROM cards
        GROUP BY topic
    """, conn)
    
    conn.close()
    return df

def get_recent_logs():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM cards ORDER BY card_id DESC LIMIT 50", conn)
    conn.close()
    return df

# Initialize immediately on import
init_db()