import io
from pypdf import PdfReader

def extract_text_from_file(uploaded_file):
    """
    Extracts raw text from PDF or TXT files.
    """
    if uploaded_file is None:
        return ""
    
    text = ""
    
    try:
        # Handle PDF
        if uploaded_file.name.lower().endswith('.pdf'):
            reader = PdfReader(uploaded_file)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
                    
        # Handle TXT/MD
        else:
            stringio = io.StringIO(uploaded_file.getvalue().decode("utf-8"))
            text = stringio.read()
            
    except Exception as e:
        return f"Error reading file: {e}"
        
    return text