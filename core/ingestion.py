import io
from pypdf import PdfReader


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Extracts raw text from PDF or TXT file bytes."""
    if not file_bytes:
        return ""

    text = ""

    try:
        if filename.lower().endswith(".pdf"):
            reader = PdfReader(io.BytesIO(file_bytes))
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        else:
            text = file_bytes.decode("utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

    return text
