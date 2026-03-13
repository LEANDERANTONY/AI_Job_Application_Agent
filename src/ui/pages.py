import streamlit as st

from src.config import DEMO_JOB_DESCRIPTION_DIR, DEMO_RESUME_DIR, list_demo_files
from src.parsers.jd import parse_jd_text
from src.parsers.linkedin import parse_linkedin_payload
from src.parsers.resume import parse_resume_document
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import (
    build_candidate_profile_from_linkedin_data,
    build_candidate_profile_from_resume,
)
from src.ui.components import render_metric_card, render_section_head


def _load_sample_resume(filename):
    with (DEMO_RESUME_DIR / filename).open("rb") as file_handle:
        return parse_resume_document(file_handle, source=f"sample:{filename}")


def _load_sample_jd(filename):
    with (DEMO_JOB_DESCRIPTION_DIR / filename).open("rb") as file_handle:
        return parse_jd_text(file_handle)


def _go_to(menu_name):
    st.session_state["current_menu"] = menu_name
    st.rerun()


def render_resume_page():
    render_section_head(
        "Resume Intake",
        "Parse an existing resume and keep it ready for tailoring.",
    )
    resume_files = list_demo_files(DEMO_RESUME_DIR, (".pdf", ".docx", ".txt"))
    resume_document = st.session_state.get("resume_document")
    left_col, right_col = st.columns([1.1, 1.2])
    with left_col:
        selected_resume = st.selectbox("Try a sample resume", ["None", *resume_files])
        if selected_resume != "None":
            resume_document = _load_sample_resume(selected_resume)
            st.session_state["resume_document"] = resume_document
            st.session_state["candidate_profile_resume"] = build_candidate_profile_from_resume(
                resume_document
            )
        uploaded_file = st.file_uploader(
            "Or upload your own resume file",
            type=["pdf", "docx", "txt"],
        )
        if uploaded_file is not None:
            resume_document = parse_resume_document(uploaded_file)
            st.session_state["resume_document"] = resume_document
            st.session_state["candidate_profile_resume"] = build_candidate_profile_from_resume(
                resume_document
            )
    with right_col:
        _render_resume_metrics(resume_document)
    if resume_document:
        st.success(f"{resume_document.filetype} resume parsed successfully.")
        st.text_area("Extracted Resume Text", resume_document.text, height=360)
        if st.button("I have a job description"):
            _go_to("Manual JD Input")


def _render_resume_metrics(resume_document):
    value = resume_document.filetype if resume_document else "Waiting"
    note = "Resume parsing is deterministic and file-based."
    render_metric_card("Resume Status", value, note)


def render_linkedin_page():
    render_section_head(
        "LinkedIn Import",
        "Import a LinkedIn export and normalize it into candidate profile data.",
    )
    st.markdown(
        """
LinkedIn does not allow direct profile import by URL for this use case.

1. Visit https://www.linkedin.com/mypreferences/d/download-my-data
2. Select "Download larger data archive"
3. Download the ZIP file from the email LinkedIn sends you
4. Upload that ZIP file here
"""
    )
    uploaded_zip = st.file_uploader("Upload LinkedIn data export (.zip)", type="zip")
    if uploaded_zip is not None:
        parsed = parse_linkedin_payload(uploaded_zip)
        st.session_state["linkedin_data"] = parsed
        st.session_state["candidate_profile_linkedin"] = build_candidate_profile_from_linkedin_data(
            parsed
        )
        st.success("LinkedIn profile parsed successfully.")

    parsed = st.session_state.get("linkedin_data")
    if not parsed:
        return

    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Skills Parsed",
            str(len(parsed.get("skills", []))),
            "Top-level skill entries from the export.",
        )
    with cols[1]:
        render_metric_card(
            "Experience Entries",
            str(len(parsed.get("experience", []))),
            "Position history recovered from the archive.",
        )
    with cols[2]:
        render_metric_card(
            "Education Entries",
            str(len(parsed.get("education", []))),
            "Education rows currently available for reuse.",
        )

    with st.expander("Preview Extracted Profile", expanded=True):
        summary = parsed.get("summary", {})
        st.markdown(f"- **Name:** {summary.get('name', 'Not provided')}")
        st.markdown(f"- **Headline:** {summary.get('headline', 'Not provided')}")
        st.markdown(f"- **Location:** {summary.get('location', 'Not provided')}")
        st.markdown(
            f"- **Top Skills:** {', '.join(parsed.get('skills', [])[:5]) or 'Not provided'}"
        )
        st.caption(
            "Candidate profile object is now prepared for downstream fit analysis and tailoring."
        )

    left_col, right_col = st.columns(2)
    with left_col:
        if st.button("I have a job description", key="linkedin_to_jd"):
            _go_to("Manual JD Input")
    with right_col:
        if st.button("Generate Resume From LinkedIn", key="linkedin_generate_resume"):
            st.info("This becomes part of the first orchestrated agent workflow.")


def render_job_search_page():
    render_section_head(
        "Job Search",
        "This stays intentionally light until the fit-analysis workflow is built.",
    )
    left_col, right_col = st.columns([1.2, 1.0])
    with left_col:
        st.text_input("Enter job title")
        st.text_input("Enter location")
        st.button("Search")
        st.info("Job search integration is still a placeholder.")
    with right_col:
        render_metric_card(
            "Search Layer",
            "Planned",
            "Real provider integrations come after fit analysis and tailoring are stable.",
        )


def render_job_description_page():
    render_section_head(
        "Job Description Intake",
        "Load a target role and convert it into structured requirements.",
    )
    demo_files = list_demo_files(DEMO_JOB_DESCRIPTION_DIR, (".txt", ".pdf", ".docx"))
    jd_text = st.session_state.get("job_description_raw", "")
    jd_source = st.session_state.get("job_description_source", "Session cache")

    left_col, right_col = st.columns([1.1, 1.2])
    with left_col:
        uploaded_jd = st.file_uploader("Upload Job Description", type=["pdf", "docx", "txt"])
        selected_sample = st.selectbox("Try a sample job description", ["None", *demo_files])
        if uploaded_jd is not None:
            jd_text = parse_jd_text(uploaded_jd)
            jd_source = "Uploaded file"
        elif selected_sample != "None":
            jd_text = _load_sample_jd(selected_sample)
            jd_source = f"Sample file: {selected_sample}"
    with right_col:
        pasted_text = st.text_area("Or paste the job description here", height=240)
        if pasted_text.strip():
            jd_text = pasted_text
            jd_source = "Pasted text"

    if jd_text:
        st.session_state["job_description_raw"] = jd_text
        st.session_state["job_description_source"] = jd_source

    st.caption(f"JD Source: {jd_source if jd_text else 'None'}")
    if not jd_text:
        return

    job_description = build_job_description_from_text(jd_text)
    st.session_state["job_description"] = job_description

    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Target Role",
            job_description.title or "Unknown",
            "Structured title extracted from the JD.",
        )
    with cols[1]:
        render_metric_card(
            "Hard Skills",
            str(len(job_description.requirements.hard_skills)),
            "Matched hard-skill keywords.",
        )
    with cols[2]:
        render_metric_card(
            "Soft Skills",
            str(len(job_description.requirements.soft_skills)),
            "Matched soft-skill keywords.",
        )

    preview_col, details_col = st.columns([1.1, 1.0])
    with preview_col:
        st.subheader("Cleaned Job Description")
        st.text_area(
            "Cleaned Text",
            job_description.cleaned_text,
            height=300,
            label_visibility="collapsed",
        )
    with details_col:
        st.subheader("Structured Job Details")
        st.markdown(f"- **Job Title:** {job_description.title}")
        st.markdown(f"- **Location:** {job_description.location or 'N/A'}")
        st.markdown(
            "- **Experience Required:** "
            f"{job_description.requirements.experience_requirement or 'N/A'}"
        )
        st.markdown(
            f"- **Hard Skills:** {', '.join(job_description.requirements.hard_skills) or 'N/A'}"
        )
        st.markdown(
            f"- **Soft Skills:** {', '.join(job_description.requirements.soft_skills) or 'N/A'}"
        )

    st.markdown(
        """
        <div class="narrative-panel">
            <h4>Why this matters</h4>
            <p>
                This structured job object is the input that the later fit-analysis and tailoring
                agents will compare against your resume or LinkedIn-derived candidate profile.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
