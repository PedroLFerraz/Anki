import os
import pickle
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# We save the "brain" to these two files
VECTORIZER_FILE = "anki_vectorizer.pkl"
MATRIX_FILE = "anki_matrix.pkl"
DATA_FILE = "anki_notes.pkl"

def save_notes_to_db(notes_list):
    """
    Takes list of dicts: [{'content': '...', 'id': '...'}, ...]
    Trains a simple TF-IDF model and saves it to disk.
    """
    if not notes_list:
        return 0
    
    # 1. Prepare Text Data
    documents = [n['content'] for n in notes_list]
    
    # 2. Convert Text to Numbers (TF-IDF)
    # This creates a matrix of "word importance"
    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform(documents)
    
    # 3. Save everything to disk (Simple Pickle dump)
    with open(VECTORIZER_FILE, 'wb') as f:
        pickle.dump(vectorizer, f)
        
    with open(MATRIX_FILE, 'wb') as f:
        pickle.dump(tfidf_matrix, f)
        
    with open(DATA_FILE, 'wb') as f:
        pickle.dump(notes_list, f)
        
    return len(documents)

def query_context(topic, n_results=15):
    """
    Finds the most similar cards using Cosine Similarity.
    """
    # Check if files exist
    if not (os.path.exists(VECTORIZER_FILE) and os.path.exists(MATRIX_FILE) and os.path.exists(DATA_FILE)):
        return []

    try:
        # 1. Load the "brain"
        with open(VECTORIZER_FILE, 'rb') as f:
            vectorizer = pickle.load(f)
        with open(MATRIX_FILE, 'rb') as f:
            tfidf_matrix = pickle.load(f)
        with open(DATA_FILE, 'rb') as f:
            notes_data = pickle.load(f)

        # 2. Convert query to numbers
        query_vec = vectorizer.transform([topic])

        # 3. Calculate similarity (Dot Product)
        # Result is an array of scores (0.0 to 1.0)
        cosine_scores = cosine_similarity(query_vec, tfidf_matrix).flatten()

        # 4. Get Top N matches
        # Sort indices by score descending
        related_indices = cosine_scores.argsort()[:-n_results-1:-1]
        
        results = []
        for i in related_indices:
            # Only return relevant results (score > 0)
            if cosine_scores[i] > 0.0:
                results.append(notes_data[i]['content'])
                
        return results

    except Exception as e:
        print(f"RAG Error: {e}")
        return []