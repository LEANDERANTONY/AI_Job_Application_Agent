import pypdf
import docx

def extract_text_from_pdf(file):
    reader = pypdf.PdfReader(file)
    text = []
    for page in reader.pages:
        text.append(page.extract_text())
    return "\n".join(text)

def extract_text_from_docx(file):
    doc = docx.Document(file)
    return "\n".join([para.text for para in doc.paragraphs])

def parse_resume(file):
    """
    Returns (text, filetype)
    """
    if file.type == "application/pdf":
        text = extract_text_from_pdf(file)
        return text, "PDF"
    elif file.type in ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/msword"]:
        text = extract_text_from_docx(file)
        return text, "DOCX"
    else:
        return None, None
