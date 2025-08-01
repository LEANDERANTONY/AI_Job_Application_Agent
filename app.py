import streamlit as st
import os
from modules import resume_parser
from modules import jd_parser

# Page title and info
st.set_page_config(page_title="AI Job Application Agent", layout="centered")
st.title("AI Job Application Agent")

st.sidebar.title("Navigation")
menu = st.sidebar.radio(
    "Go to:",
    (
        "Upload Resume",
        "Build from LinkedIn",
        "Job Search",
        "Manual JD Input"
    )
)

if menu == "Upload Resume":
    st.header("Upload Resume")
    st.write("Upload your existing resume (PDF or DOCX) for tailoring.")

    resume_dir = "static/demo_resume"
    resume_files = [f for f in os.listdir(resume_dir) if f.lower().endswith((".pdf", ".docx", ".txt"))]

    resume_text = None
    filetype = None

    # === Sample Resume Selector ===
    if resume_files:
        selected_resume = st.selectbox("Try a Sample Resume", ["None"] + resume_files)
        if selected_resume != "None":
            sample_path = os.path.join(resume_dir, selected_resume)
            with open(sample_path, "rb") as f:
                resume_text, filetype = resume_parser.parse_resume(f)

    # === File Upload Option ===
    uploaded_file = st.file_uploader("Or upload your own resume file", type=["pdf", "docx"])
    if uploaded_file is not None:
        resume_text, filetype = resume_parser.parse_resume(uploaded_file)

    # === Output Preview ===
    if resume_text:
        st.success(f"{filetype} parsed! See preview below:")
        st.text_area("Extracted Resume Text", resume_text, height=300)
    elif uploaded_file or selected_resume != "None":
        st.error("Unsupported file type or failed to extract text.")


elif menu == "Build from LinkedIn":
    st.header("Build Resume from LinkedIn")
    st.write("Upload your LinkedIn data file or paste your public profile URL.")
    linkedin_file = st.file_uploader("Upload LinkedIn data (optional)", type=["csv", "json"])
    linkedin_url = st.text_input("Or paste your LinkedIn profile URL")
    if linkedin_file or linkedin_url:
        st.success("LinkedIn data input received! (Resume builder coming soon...)")

elif menu == "Job Search":
    st.header("Job Search & Scrape")
    st.write("Search jobs using APIs and auto-fill job descriptions.")
    st.text_input("Enter job title")
    st.text_input("Enter location")
    st.button("Search (API Integration coming soon)")
    st.info("Job search results and scraping will be shown here.")

elif menu == "Manual JD Input":
    st.header("Manual Job Description Input")
    st.write("Upload or paste a job description (.pdf, .docx, or .txt)")

    demo_dir = "static/demo_job_description"
    demo_files = [f for f in os.listdir(demo_dir) if f.lower().endswith((".txt", ".pdf", ".docx"))]

    jd_text = None

    # === Sample File Selector ===
    if demo_files:
        sample_choice = st.selectbox("Try a Sample JD", ["None"] + demo_files)

        if sample_choice != "None":
            sample_path = os.path.join(demo_dir, sample_choice)
            with open(sample_path, "rb") as f:
                jd_text = jd_parser.parse_jd_file(f)

    # === File Uploader ===
    uploaded_jd = st.file_uploader("Upload Job Description", type=["pdf", "docx", "txt"])
    if uploaded_jd is not None:
        jd_text = jd_parser.parse_jd_file(uploaded_jd)

    # === Paste Box ===
    jd_pasted = st.text_area("...Or paste the job description here", height=300)
    if jd_pasted:
        jd_text = jd_pasted

    # === Display & Extract ===
    if jd_text:
        cleaned_jd = jd_parser.clean_text(jd_text)
        extracted_info = jd_parser.extract_job_details(cleaned_jd)

        st.subheader("🧹 Cleaned Job Description")
        st.text_area("Cleaned Text", cleaned_jd, height=250)

        st.subheader("📌 Extracted Details")
        st.markdown(f"- **Job Title:** {extracted_info['title']}")
        st.markdown(f"- **Location:** {extracted_info.get('location', 'N/A')}")
        st.markdown(f"- **Experience Required:** {extracted_info.get('experience_required', 'N/A')}")

        st.markdown(f"- **Hard Skills:** {', '.join(extracted_info['skills']) or 'N/A'}")
        st.markdown(f"- **Soft Skills:** {', '.join(extracted_info['soft_skills']) or 'N/A'}")





