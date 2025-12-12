import streamlit as st
import re

def get_secret(key):
    """Safely get secret from streamlit secrets."""
    if key in st.secrets:
        return st.secrets[key]
    return None

def smart_parse(raw_text, fields):
    """Parses the pipe-separated text into a list of dicts."""
    parsed_cards = []
    # Clean markdown
    clean_text = raw_text.replace("```markdown", "").replace("```text", "").replace("```", "").strip()
    lines = clean_text.split('\n')
    expected_count = len(fields)
    
    for line in lines:
        # Remove list markers like "1.", "-", "*"
        line = re.sub(r'^[\d\)\.\-\*]+\s*', '', line).strip()
        if not line or "|" not in line: continue 
            
        parts = [p.strip() for p in line.split('|')]
        
        # Handle trailing/missing pipes
        if len(parts) == expected_count + 1 and parts[-1] == "": parts.pop()
        if len(parts) == expected_count - 1: parts.append("") 

        if len(parts) == expected_count:
            row = {fields[i]: parts[i] for i in range(expected_count)}
            row["✅"] = True 
            parsed_cards.append(row)
    return parsed_cards