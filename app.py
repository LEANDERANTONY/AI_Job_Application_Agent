import streamlit as st
import os
from modules import resume_parser
from modules import jd_parser

# Page title and info
st.set_page_config(page_title="AI Job Application Agent", layout="centered")
st.title("AI Job Application Agent")

st.sidebar.title("Navigation")

# Set menu from redirect if exists
if "redirect_to" in st.session_state:
    default_menu = st.session_state.pop("redirect_to")
    st.session_state["current_menu"] = default_menu  # Make sure current menu updates
else:
    default_menu = st.session_state.get("current_menu", "Upload Resume")

menu_options = ["Upload Resume", "Build from LinkedIn", "Job Search", "Manual JD Input"]
menu = st.sidebar.radio(
    "Go to:",
    menu_options,
    index=menu_options.index(default_menu)
)
st.session_state["current_menu"] = menu

if menu == "Upload Resume":
    st.header("Upload Resume")
    st.write("Upload your existing resume (PDF or DOCX) for tailoring.")

    from modules import resume_parser

    resume_dir = "static/demo_resume"
    resume_files = [f for f in os.listdir(resume_dir) if f.lower().endswith((".pdf", ".docx", ".txt"))]

    resume_text = None
    filetype = None

    # === Session fallback ===
    cached_resume = st.session_state.get("resume_data")
    if cached_resume:
        resume_text = cached_resume["text"]
        filetype = cached_resume["filetype"]

    # === Sample Resume Selector ===
    selected_resume = st.selectbox("Try a Sample Resume", ["None"] + resume_files)
    if selected_resume != "None":
        sample_path = os.path.join(resume_dir, selected_resume)
        with open(sample_path, "rb") as f:
            resume_text, filetype = resume_parser.parse_resume(f)
        st.session_state["resume_data"] = {"text": resume_text, "filetype": filetype}

    # === File Upload Option ===
    uploaded_file = st.file_uploader("Or upload your own resume file", type=["pdf", "docx"])
    if uploaded_file is not None:
        resume_text, filetype = resume_parser.parse_resume(uploaded_file)
        if resume_text:
            st.session_state["resume_data"] = {"text": resume_text, "filetype": filetype}
        else:
            st.error("Unsupported file type or failed to extract text.")

    # === Output Preview ===
    if resume_text:
        st.success(f"{filetype} parsed! See preview below:")
        st.text_area("Extracted Resume Text", resume_text, height=300)


elif menu == "Build from LinkedIn":
    st.header("🔗 Import LinkedIn Profile")

    st.markdown("""
    LinkedIn does **not** allow apps to access your profile directly via URL due to API restrictions and Terms of Service.

    👉 To use your LinkedIn profile for resume generation, please upload your exported data archive:

    ### 📥 How to Export Your LinkedIn Data:
    1. Visit [https://www.linkedin.com/mypreferences/d/download-my-data] 
    2. Select **"Download larger data archive"** (includes experience, education, skills)
    3. Download the `.zip` file from your email
    4. Upload it below
    or watch this short video tutorial https://www.youtube.com/watch?v=2Z7h_WHsFzI
    """)

    uploaded_zip = st.file_uploader("Upload LinkedIn Data Export (.zip)", type="zip")

    from modules import linkedin_parser

    # New Upload
    if uploaded_zip:
        try:
            parsed = linkedin_parser.parse_linkedin_zip(uploaded_zip)
            st.session_state["linkedin_data"] = parsed
            st.success("✅ LinkedIn profile parsed successfully!")
        except Exception as e:
            st.error("❌ Failed to parse LinkedIn export. Please ensure it's the correct .zip format.")
            st.exception(e)

    # Use cached data
    parsed = st.session_state.get("linkedin_data")
    if parsed:
        with st.expander("🔍 Preview Extracted Info"):
            summary = parsed.get("summary", {})
            st.markdown(f"- **Name:** {summary.get('name', 'Not Provided')}")
            st.markdown(f"- **Headline:** {summary.get('headline', 'Not Provided')}")
            st.markdown(f"- **Location:** {summary.get('location', 'Not Provided')}")
            st.markdown(f"- **Top Skills:** {', '.join(parsed.get('skills', [])[:5]) or 'Not Provided'}")

            st.markdown("### 💼 Experience")
            experience = parsed.get("experience", [])
            if experience:
                for job in experience:
                    st.markdown(f"- **{job.get('title', 'N/A')}** at **{job.get('company', 'N/A')}**, {job.get('location', 'N/A')}")
            else:
                st.markdown("Not Provided")

            st.markdown("### 🎓 Education")
            education = parsed.get("education", [])
            if education:
                for edu in education:
                    st.markdown(f"- **{edu.get('degree', 'N/A')}** from **{edu.get('school', 'N/A')}**")
            else:
                st.markdown("Not Provided")

            st.markdown("### 🎯 Job Preferences")
            prefs = parsed.get("preferences", {})
            if prefs:
                for k, v in prefs.items():
                    st.markdown(f"- **{k}:** {v}")
            else:
                st.markdown("Not Provided")

            st.markdown("### 📚 Publications")
            pubs = parsed.get("publications", [])
            if pubs:
                for pub in pubs:
                    st.markdown(f"- **{pub.get('title', 'N/A')}**, {pub.get('publisher', 'N/A')} ({pub.get('date', 'N/A')})")
            else:
                st.markdown("Not Provided")

        st.markdown("---")
        col1, col2 = st.columns(2)

        with col1:
            if st.button("📄 I have a Job Description"):
                st.session_state["redirect_to"] = "Manual JD Input"
                st.rerun()

        with col2:
            if st.button("⚙️ Proceed to Generate Resume from LinkedIn Profile"):
                st.info("🔧 LLM connection for resume generation is being built... Stay tuned!")


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

    # === Upload first so it's available later ===
    uploaded_jd = st.file_uploader("Upload Job Description", type=["pdf", "docx", "txt"])

    # === Sample File Selector ===
    if demo_files:
        sample_choice = st.selectbox("Try a Sample JD", ["None"] + demo_files)
        if sample_choice != "None":
            sample_path = os.path.join(demo_dir, sample_choice)
            with open(sample_path, "rb") as f:
                jd_text = jd_parser.parse_jd_file(f)

    # === Use Uploaded File or Fallback to Saved Session ===
    if uploaded_jd is not None:
        # ✅ Store in session so rerun doesn't lose it
        st.session_state["uploaded_jd_file"] = uploaded_jd
        jd_text = jd_parser.parse_jd_file(uploaded_jd)

    elif "uploaded_jd_file" in st.session_state:
        jd_text = jd_parser.parse_jd_file(st.session_state["uploaded_jd_file"])
    
    st.markdown(f"📂 **JD Source:** {'Uploaded file' if uploaded_jd else 'Session cache' if 'uploaded_jd_file' in st.session_state else 'None'}")

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

# ⏪ Handle any late redirection AFTER all rendering logic
if "redirect_to" in st.session_state:
    st.session_state["current_menu"] = st.session_state.pop("redirect_to")
    st.rerun()

