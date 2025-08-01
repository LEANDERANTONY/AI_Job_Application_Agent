import streamlit as st
import pypdf
import docx
import mimetypes

def extract_text_from_pdf(file):
    reader = pypdf.PdfReader(file)
    text = []
    for page in reader.pages:
        text.append(page.extract_text())
    return "\n".join(text)

def extract_text_from_docx(file):
    doc = docx.Document(file)
    return "\n".join([para.text for para in doc.paragraphs])

@st.cache_data(show_spinner="Parsing resume...")
def parse_resume(file):
    """
    Parses PDF or DOCX resume and returns (text, filetype).
    Supports both Streamlit file uploads and local file objects.
    """
    if hasattr(file, "type"):  # Streamlit uploader
        file_type = file.type
    else:  # Sample file (BufferedReader)
        mime_guess, _ = mimetypes.guess_type(file.name)
        file_type = mime_guess or "application/octet-stream"

    if file_type == "application/pdf":
        text = extract_text_from_pdf(file)
        return text, "PDF"

    elif file_type in [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword"
    ]:
        text = extract_text_from_docx(file)
        return text, "DOCX"

    else:
        return None, None
