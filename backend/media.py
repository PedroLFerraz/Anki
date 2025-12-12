import requests
import base64
import os
import re
import tempfile
import time
import random
import streamlit as st
from gtts import gTTS
from duckduckgo_search import DDGS 
from urllib.parse import urlparse
from .anki import store_media_file

# --- 1. SEARCH ENGINES ---

def search_wikimedia(query):
    """
    Primary Search for Art/History.
    Includes proper User-Agent to avoid JSON Decode Errors.
    """
    url = "https://commons.wikimedia.org/w/api.php"
    
    clean_query = query.replace("painting", "").strip()
    
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": f"{clean_query} filetype:bitmap",
        "gsrlimit": 3,
        "prop": "imageinfo",
        "iiprop": "url"
    }
    
    # FIX: Wikimedia requires a User-Agent or it blocks you
    headers = {
        "User-Agent": "AnkiCardGenerator/1.0 (https://github.com/yourname/anki-agent; your@email.com)"
    }
    
    candidates = []
    try:
        # 30% chance to sleep 0.1s just to be safe
        if random.random() > 0.7: time.sleep(0.1)
        
        # Added headers=headers here
        res = requests.get(url, params=params, headers=headers, timeout=5)
        
        # Check if request succeeded before trying to parse JSON
        if res.status_code == 200:
            data = res.json()
            pages = data.get("query", {}).get("pages", {})
            for page_id in pages:
                image_info = pages[page_id].get('imageinfo', [])
                if image_info:
                    candidates.append(image_info[0]['url'])
        else:
            print(f"Wiki Status Error: {res.status_code}")
                
    except Exception as e:
        print(f"Wiki Connection Error: {e}")
        
    return candidates

def search_duckduckgo(query):
    """
    Secondary Search.
    Includes Exponential Backoff to fix '202 Ratelimit'.
    """
    candidates = []
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            # Wait longer on each retry: 2s -> 4s -> 8s
            wait_time = (2 ** attempt) + random.uniform(0, 1)
            time.sleep(wait_time)
            
            with DDGS() as ddgs:
                results = list(ddgs.images(
                    keywords=query, 
                    region="wt-wt", 
                    safesearch="on", 
                    max_results=2
                ))
                if results:
                    candidates = [r['image'] for r in results]
                    return candidates
                    
        except Exception as e:
            print(f"DDG Attempt {attempt+1} failed: {e}")
            
    return []

def search_images(query):
    """
    Master Search: Wiki -> then DDG
    """
    # 1. Try Wiki (Best for Art)
    candidates = search_wikimedia(query)
    
    # 2. If we have fewer than 2 candidates, try DuckDuckGo
    if len(candidates) < 2:
        try:
            ddg_results = search_duckduckgo(query)
            candidates.extend(ddg_results)
        except:
            pass
        
    return candidates

# --- 2. DOWNLOADER ---

def download_image_candidates(urls):
    """
    Tries to download from a list of URLs until one works.
    """
    if isinstance(urls, str): urls = [urls]
        
    for url in urls:
        try:
            domain = urlparse(url).netloc
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': f"https://{domain}/", 
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                # Check if it's actually an image
                content_type = response.headers.get('Content-Type', '').lower()
                if 'image' in content_type:
                    filename = f"web_img_{abs(hash(url))}.jpg"
                    b64_data = base64.b64encode(response.content).decode('utf-8')
                    
                    saved_name = store_media_file(filename, b64_data)
                    if saved_name:
                        return saved_name
        except Exception:
            continue
            
    return None

# --- 3. AUDIO ---

def generate_audio(text, lang='en'):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
            tts = gTTS(text=text, lang=lang)
            tts.save(fp.name)
            temp_path = fp.name
        
        with open(temp_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode('utf-8')
        os.remove(temp_path)
        
        safe_name = re.sub(r'[^a-zA-Z0-9]', '', text[:10])
        filename = f"gemini_audio_{safe_name}_{abs(hash(text))}.mp3"
        return store_media_file(filename, b64_data)
    except Exception as e:
        st.write(f"⚠️ Audio Error: {e}")
        return None