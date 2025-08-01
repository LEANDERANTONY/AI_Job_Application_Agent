import re
import streamlit as st
import docx
import pypdf
import mimetypes

@st.cache_data(show_spinner="Parsing uploaded job description...")
def parse_jd_file(file):
    """Handles .txt, .pdf, .docx JD uploads and extracts raw text"""

    if hasattr(file, "type"):  # Streamlit uploaded file
        file_type = file.type   
    else:  # Local file from disk (sample JD)
        mime_guess, _ = mimetypes.guess_type(file.name)
        file_type = mime_guess or "application/octet-stream"


    if file_type == "text/plain":
        return file.read().decode("utf-8")

    elif file_type == "application/pdf":
        pdf = pypdf.PdfReader(file)
        return "\n".join([page.extract_text() or "" for page in pdf.pages])

    elif file_type in [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword"
    ]:
        doc = docx.Document(file)
        return "\n".join([para.text for para in doc.paragraphs])

    else:
        return "Unsupported file type."

@st.cache_data(show_spinner="Cleaning job description...")
def clean_text(text):
    """Basic cleaning: strip, normalize spacing, remove symbols"""
    text = text.replace('\xa0', ' ')
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[•\-\*\●]', '', text)
    return text.strip()

@st.cache_data(show_spinner="Extracting job info...")
def extract_job_details(text):
    """Extract title, skills, location, experience, soft skills"""
    keywords = {
        "skills": [
            "Python", "SQL", "Machine Learning", "Data Analysis", "Deep Learning",
            "NLP", "AWS", "Excel", "TensorFlow", "PyTorch", "Power BI", "Docker", "Kubernetes"
        ],
        "soft_skills": [
            "communication", "teamwork", "problem-solving", "leadership",
            "adaptability", "time management", "collaboration", "critical thinking"
        ],
    }

    extracted = {
        "title": None,
        "location": None,
        "experience_required": None,
        "skills": [],
        "soft_skills": []
    }

    lines = text.split("\n")
    if lines:
        extracted["title"] = lines[0].strip()

    lowered = text.lower()
    for skill in keywords["skills"]:
        if skill.lower() in lowered:
            extracted["skills"].append(skill)

    for soft in keywords["soft_skills"]:
        if soft.lower() in lowered:
            extracted["soft_skills"].append(soft)

    loc_match = re.search(r"Location\s*[:\-]?\s*([A-Za-z\s,]+)", text, re.I)
    if loc_match:
        extracted["location"] = loc_match.group(1).strip()

    exp_match = re.search(r"(\d+\+?)\s*(years?|yrs?)\s*(of)?\s*(experience)?", text, re.I)
    if exp_match:
        extracted["experience_required"] = exp_match.group(0).strip()

    return extracted
