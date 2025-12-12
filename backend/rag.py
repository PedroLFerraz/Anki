# backend/rag.py
import os
import pickle
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

VECTORIZER_FILE = "anki_vectorizer.pkl"
MATRIX_FILE = "anki_matrix.pkl"
DATA_FILE = "anki_notes.pkl"

def save_notes_to_db(notes_list):
    if not notes_list: return 0
    documents = [n['content'] for n in notes_list]
    
    # Enable n-grams (1,2) to catch phrases like "Window Function" better
    vectorizer = TfidfVectorizer(stop_words='english', ngram_range=(1, 2))
    tfidf_matrix = vectorizer.fit_transform(documents)
    
    with open(VECTORIZER_FILE, 'wb') as f: pickle.dump(vectorizer, f)
    with open(MATRIX_FILE, 'wb') as f: pickle.dump(tfidf_matrix, f)
    with open(DATA_FILE, 'wb') as f: pickle.dump(notes_list, f)
    return len(documents)

def query_context(topic, n_results=30): # Increased from 15 to 30
    if not (os.path.exists(VECTORIZER_FILE) and os.path.exists(MATRIX_FILE) and os.path.exists(DATA_FILE)):
        return []

    try:
        with open(VECTORIZER_FILE, 'rb') as f: vectorizer = pickle.load(f)
        with open(MATRIX_FILE, 'rb') as f: tfidf_matrix = pickle.load(f)
        with open(DATA_FILE, 'rb') as f: notes_data = pickle.load(f)

        query_vec = vectorizer.transform([topic])
        cosine_scores = cosine_similarity(query_vec, tfidf_matrix).flatten()
        related_indices = cosine_scores.argsort()[:-n_results-1:-1]
        
        results = []
        for i in related_indices:
            # Lower threshold to catch loosely related cards
            if cosine_scores[i] > 0.1: 
                results.append(notes_data[i]['content'])
        return results
    except Exception as e:
        print(f"RAG Error: {e}")
        return []