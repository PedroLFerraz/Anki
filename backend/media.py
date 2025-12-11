import requests
import base64
import os
import re
import tempfile
import time
import random  # <--- NEW: For random delays
import streamlit as st
from gtts import gTTS
from duckduckgo_search import DDGS 
from urllib.parse import urlparse
from .anki import store_media_file

def search_wikimedia(query):
    """
    Fallback: Great for Art/Paintings/History.
    """
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrnamespace": "6", "gsrsearch": f"filetype:bitmap {query}",
        "gsrlimit": 1, "prop": "imageinfo", "iiprop": "url"
    }
    try:
        # Add a tiny delay to be polite to Wikipedia API too
        time.sleep(0.2)
        res = requests.get(url, params=params, timeout=5).json()
        pages = res.get("query", {}).get("pages", {})
        if pages:
            first_key = next(iter(pages))
            return pages[first_key]['imageinfo'][0]['url']
    except:
        pass
    return None

def search_images(query):
    """
    Returns a LIST of up to 3 candidate URLs.
    Includes Retries and Random Delays to fix '202 Ratelimit'.
    """
    candidates = []
    
    # 1. Try DuckDuckGo (With Retry Logic)
    max_retries = 2
    for attempt in range(max_retries):
        try:
            # JITTER: Sleep random time (0.5s to 1.5s) to simulate human speed
            # This is the best way to prevent 202 errors
            time.sleep(random.uniform(0.5, 1.5))
            
            with DDGS() as ddgs:
                results = list(ddgs.images(
                    keywords=query, 
                    region="wt-wt", 
                    safesearch="on", 
                    max_results=2 # Fetch 2 from DDG
                ))
                if results:
                    candidates.extend([r['image'] for r in results])
                    break # Success, stop retrying
                    
        except Exception as e:
            print(f"DDG Attempt {attempt+1} failed: {e}")
            if attempt < max_retries - 1:
                # If we failed, wait longer (3 seconds) before retrying
                time.sleep(3)
            else:
                print("DDG failed after retries.")

    # 2. Always check Wikimedia too (Great for Art)
    # Even if DDG worked, we add a Wikimedia option because it's high quality for paintings
    try:
        wiki_url = search_wikimedia(query)
        if wiki_url:
            candidates.append(wiki_url)
    except:
        pass

    return candidates

def download_image_candidates(urls):
    """
    Tries to download from a list of URLs. Returns the first success.
    """
    if isinstance(urls, str):
        urls = [urls]
        
    for url in urls:
        try:
            # 1. Fake Headers based on domain
            domain = urlparse(url).netloc
            base_url = f"https://{domain}/"

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': base_url, 
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
            }
            
            # 2. Attempt Download
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # 3. If successful, save and return immediately
            filename = f"web_img_{abs(hash(url))}.jpg"
            b64_data = base64.b64encode(response.content).decode('utf-8')
            
            saved_name = store_media_file(filename, b64_data)
            if saved_name:
                return saved_name
                
        except Exception:
            continue
            
    return None

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