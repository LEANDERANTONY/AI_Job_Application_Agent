import streamlit as st
from modules import resume_parser

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
    uploaded_file = st.file_uploader("Choose your resume file", type=["pdf", "docx"])
    if uploaded_file:
        text, filetype = resume_parser.parse_resume(uploaded_file)
        if text:
            st.success(f"{filetype} parsed! See preview below:")
            st.text_area("Extracted Resume Text", text, height=300)
        else:
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
    st.write("Paste or upload a job description to tailor your resume.")
    jd_text = st.text_area("Paste the job description here")
    jd_file = st.file_uploader("Or upload job description (PDF/DOCX)", type=["pdf", "docx"])
    if jd_text or jd_file:
        st.success("Job description received! (Processing coming soon...)")

st.sidebar.markdown("---")
st.sidebar.info("Project setup complete! Ready for module-by-module build.")




