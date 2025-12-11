import requests
import base64
import os
import re
import tempfile
import time
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
    """
    candidates = []
    
    # 1. Try DuckDuckGo (Get 3 options)
    try:
        with DDGS() as ddgs:
            results = list(ddgs.images(
                keywords=query, 
                region="wt-wt", 
                safesearch="on", 
                max_results=3 # <--- Fetch 3 candidates
            ))
            if results:
                candidates = [r['image'] for r in results]
    except Exception as e:
        print(f"DDG Error: {e}")
        time.sleep(1)

    # 2. Add Wikimedia as a backup candidate
    if not candidates:
        wiki_url = search_wikimedia(query)
        if wiki_url:
            candidates.append(wiki_url)

    return candidates

def download_image_candidates(urls):
    """
    Tries to download from a list of URLs. Returns the first success.
    """
    # Ensure it's a list
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
            
            # 3. If successful, save and return immediately (Stop looping)
            filename = f"web_img_{abs(hash(url))}.jpg"
            b64_data = base64.b64encode(response.content).decode('utf-8')
            
            saved_name = store_media_file(filename, b64_data)
            if saved_name:
                return saved_name
                
        except Exception:
            # If this URL failed, just silently continue to the next one
            continue
            
    # If we tried all URLs and all failed:
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