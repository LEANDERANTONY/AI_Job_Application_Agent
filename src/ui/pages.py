import hashlib
import json
from dataclasses import asdict

import streamlit as st

from src.agents.orchestrator import ApplicationOrchestrator
from src.config import DEMO_JOB_DESCRIPTION_DIR, DEMO_RESUME_DIR, list_demo_files
from src.errors import ExportError
from src.exporters import export_markdown_bytes, export_pdf_bytes
from src.openai_service import OpenAIService
from src.parsers.jd import parse_jd_text
from src.parsers.linkedin import parse_linkedin_payload
from src.parsers.resume import parse_resume_document
from src.report_builder import build_application_report
from src.schemas import (
    AgentWorkflowResult,
    ApplicationReport,
    CandidateProfile,
    FitAnalysis,
    TailoredResumeDraft,
)
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import (
    build_candidate_profile_from_linkedin_data,
    build_candidate_profile_from_resume,
    merge_candidate_profiles,
)
from src.services.tailoring_service import build_tailored_resume_draft
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


def _render_list(title, items, empty_state):
    st.markdown(f"**{title}**")
    if items:
        for item in items:
            st.markdown(f"- {item}")
    else:
        st.caption(empty_state)


def _workflow_signature(candidate_profile, job_description, fit_analysis, tailored_draft):
    payload = {
        "candidate_profile": asdict(candidate_profile),
        "job_description": asdict(job_description),
        "fit_analysis": asdict(fit_analysis),
        "tailored_draft": asdict(tailored_draft),
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _report_signature(report):
    raw = json.dumps(
        {
            "title": report.title,
            "summary": report.summary,
            "markdown": report.markdown,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_active_candidate_profile():
    merged_profile = merge_candidate_profiles(
        st.session_state.get("candidate_profile_resume"),
        st.session_state.get("candidate_profile_linkedin"),
    )
    if merged_profile:
        st.session_state["candidate_profile"] = merged_profile
    return merged_profile


def _render_resume_metrics(resume_document):
    value = resume_document.filetype if resume_document else "Waiting"
    note = "Resume parsing is deterministic and file-based."
    render_metric_card("Resume Status", value, note)


def _render_profile_snapshot(candidate_profile: CandidateProfile):
    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Profile Source",
            candidate_profile.source or "Unknown",
            "Resume and LinkedIn signals are merged when both exist.",
        )
    with cols[1]:
        render_metric_card(
            "Skills Available",
            str(len(candidate_profile.skills)),
            "Detected or imported skills available for matching.",
        )
    with cols[2]:
        render_metric_card(
            "Experience Entries",
            str(len(candidate_profile.experience)),
            "Structured experience is strongest when LinkedIn is imported.",
        )

    with st.expander("Normalized Candidate Snapshot", expanded=False):
        st.markdown(f"- **Name:** {candidate_profile.full_name or 'Not inferred yet'}")
        st.markdown(f"- **Location:** {candidate_profile.location or 'Not inferred yet'}")
        st.markdown(
            f"- **Skills:** {', '.join(candidate_profile.skills[:8]) or 'No explicit skills detected'}"
        )
        _render_list(
            "Source Signals",
            candidate_profile.source_signals,
            "No source signals available yet.",
        )


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
        _render_profile_snapshot(st.session_state["candidate_profile_resume"])
        st.text_area("Extracted Resume Text", resume_document.text, height=320)
        if st.button("I have a job description"):
            _go_to("Manual JD Input")


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

    _render_profile_snapshot(st.session_state["candidate_profile_linkedin"])

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


def _render_fit_snapshot(
    candidate_profile: CandidateProfile,
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
):
    st.markdown("---")
    render_section_head(
        "Readiness Snapshot",
        "Deterministic fit analysis built from the normalized candidate profile and JD.",
    )

    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Fit Score",
            f"{fit_analysis.overall_score}/100",
            "Weighted from matched skills and experience signals.",
        )
    with cols[1]:
        render_metric_card(
            "Readiness",
            fit_analysis.readiness_label,
            fit_analysis.target_role or "Target role inferred from the JD.",
        )
    with cols[2]:
        render_metric_card(
            "Missing Hard Skills",
            str(len(fit_analysis.missing_hard_skills)),
            "These are the highest-friction tailoring gaps right now.",
        )

    st.markdown(
        """
        <div class="narrative-panel">
            <h4>Experience Signal</h4>
            <p>{signal}</p>
        </div>
        """.format(signal=fit_analysis.experience_signal),
        unsafe_allow_html=True,
    )

    left_col, right_col = st.columns(2)
    with left_col:
        _render_list(
            "Matched Hard Skills",
            fit_analysis.matched_hard_skills,
            "No matched hard-skill evidence yet.",
        )
        _render_list(
            "Strengths",
            fit_analysis.strengths,
            "No strengths have been surfaced yet.",
        )
        _render_list(
            "Highlighted Skills For Resume",
            tailored_draft.highlighted_skills,
            "No highlighted skills prepared yet.",
        )
    with right_col:
        _render_list(
            "Missing Hard Skills",
            fit_analysis.missing_hard_skills,
            "Hard-skill coverage is complete for the extracted JD keywords.",
        )
        _render_list(
            "Gaps",
            fit_analysis.gaps,
            "No major gaps surfaced from the current inputs.",
        )
        _render_list(
            "Recommendations",
            fit_analysis.recommendations,
            "No recommendations generated yet.",
        )

    with st.expander("Tailored Resume Draft Preview", expanded=True):
        st.markdown("**Professional Summary Draft**")
        st.write(tailored_draft.professional_summary)
        _render_list(
            "Priority Bullets",
            tailored_draft.priority_bullets,
            "No priority bullets generated yet.",
        )
        _render_list(
            "Gap Mitigation Steps",
            tailored_draft.gap_mitigation_steps,
            "No mitigation steps generated yet.",
        )
        st.caption(
            "This is still deterministic guidance. The later agent layer will rewrite these sections more intelligently while staying grounded."
        )


def _render_agent_workflow_result(agent_result: AgentWorkflowResult):
    st.markdown("---")
    render_section_head(
        "Supervised Agent Workflow",
        "Specialist agents refine the deterministic baseline while preserving grounded output.",
    )

    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Execution Mode",
            "OpenAI" if agent_result.mode == "openai" else "Fallback",
            "Explicit model calls run only on button press.",
        )
    with cols[1]:
        render_metric_card(
            "Review Status",
            "Approved" if agent_result.review.approved else "Needs Revision",
            "The review agent is the final quality gate.",
        )
    with cols[2]:
        render_metric_card(
            "Model",
            agent_result.model,
            "Fallback means deterministic logic only.",
        )

    with st.expander("Profile and Job Positioning", expanded=True):
        st.markdown("**Profile Positioning Headline**")
        st.write(agent_result.profile.positioning_headline or "No positioning headline produced.")
        _render_list(
            "Evidence Highlights",
            agent_result.profile.evidence_highlights,
            "No evidence highlights produced.",
        )
        _render_list(
            "Strengths",
            agent_result.profile.strengths,
            "No strengths produced.",
        )
        _render_list(
            "Job Messaging Guidance",
            agent_result.job.messaging_guidance,
            "No job messaging guidance produced.",
        )

    left_col, right_col = st.columns(2)
    with left_col:
        _render_list(
            "Fit Summary",
            [agent_result.fit.fit_summary],
            "No fit summary produced.",
        )
        _render_list(
            "Top Matches",
            agent_result.fit.top_matches,
            "No top matches produced.",
        )
        _render_list(
            "Interview Themes",
            agent_result.fit.interview_themes,
            "No interview themes produced.",
        )
    with right_col:
        _render_list(
            "Rewritten Bullet Ideas",
            agent_result.tailoring.rewritten_bullets,
            "No rewritten bullets produced.",
        )
        _render_list(
            "Highlighted Skills",
            agent_result.tailoring.highlighted_skills,
            "No highlighted skills produced.",
        )
        _render_list(
            "Cover Letter Themes",
            agent_result.tailoring.cover_letter_themes,
            "No cover letter themes produced.",
        )

    with st.expander("Review Notes", expanded=True):
        st.markdown("**Tailored Professional Summary**")
        st.write(agent_result.tailoring.professional_summary)
        _render_list(
            "Grounding Issues",
            agent_result.review.grounding_issues,
            "No grounding issues detected.",
        )
        _render_list(
            "Revision Requests",
            agent_result.review.revision_requests,
            "No revisions requested.",
        )
        _render_list(
            "Final Notes",
            agent_result.review.final_notes,
            "No final notes produced.",
        )


def _render_report_package(report: ApplicationReport, agent_result: AgentWorkflowResult = None):
    st.markdown("---")
    render_section_head(
        "Application Package",
        "Deterministic final assembly for export and recruiter-facing review.",
    )

    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Package Mode",
            "Agent-Enhanced" if agent_result else "Deterministic",
            "The report builder assembles a stable package from current workflow outputs.",
        )
    with cols[1]:
        render_metric_card(
            "Export Formats",
            "Markdown + PDF",
            "Markdown stays editable. PDF is the polished package for sharing.",
        )
    with cols[2]:
        render_metric_card(
            "Report Status",
            "Ready",
            report.summary,
        )

    with st.expander("Preview Application Package", expanded=False):
        st.text_area(
            "Package Preview",
            report.markdown,
            height=360,
            label_visibility="collapsed",
        )

    signature = _report_signature(report)
    if st.session_state.get("application_report_signature") != signature:
        st.session_state["application_report_signature"] = signature
        st.session_state.pop("application_report_pdf_bytes", None)

    download_col, pdf_col = st.columns(2)
    with download_col:
        st.download_button(
            "Download Markdown Package",
            data=export_markdown_bytes(report),
            file_name=report.filename_stem + ".md",
            mime="text/markdown",
            key="download_markdown_package",
        )
    with pdf_col:
        if st.session_state.get("application_report_pdf_bytes") is None:
            if st.button("Prepare PDF Package", key="prepare_pdf_package"):
                try:
                    with st.spinner("Generating PDF package..."):
                        st.session_state["application_report_pdf_bytes"] = export_pdf_bytes(report)
                except ExportError as error:
                    st.warning(error.user_message)
        else:
            st.download_button(
                "Download PDF Package",
                data=st.session_state["application_report_pdf_bytes"],
                file_name=report.filename_stem + ".pdf",
                mime="application/pdf",
                key="download_pdf_package",
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
            f"- **Must-Have Signals:** {len(job_description.requirements.must_haves)}"
        )
        st.markdown(
            f"- **Nice-To-Have Signals:** {len(job_description.requirements.nice_to_haves)}"
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

    candidate_profile = _get_active_candidate_profile()
    if not candidate_profile:
        st.info(
            "Load a resume or LinkedIn export first. Once candidate data exists, this page will render a fit snapshot and tailored resume guidance."
        )
        return

    fit_analysis = build_fit_analysis(candidate_profile, job_description)
    tailored_draft = build_tailored_resume_draft(
        candidate_profile,
        job_description,
        fit_analysis,
    )
    st.session_state["fit_analysis"] = fit_analysis
    st.session_state["tailored_resume_draft"] = tailored_draft
    _render_fit_snapshot(candidate_profile, fit_analysis, tailored_draft)

    signature = _workflow_signature(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
    )
    if st.session_state.get("agent_workflow_signature") != signature:
        st.session_state.pop("agent_workflow_result", None)
        st.session_state["agent_workflow_signature"] = signature

    st.markdown("---")
    mode_label = "AI-assisted" if OpenAIService().is_available() else "Fallback-ready"
    st.caption(
        "Run the supervised workflow explicitly to avoid accidental model calls on every rerun."
    )
    if st.button("Run supervised agent workflow", key="run_supervised_workflow"):
        orchestrator = ApplicationOrchestrator()
        st.session_state["agent_workflow_result"] = orchestrator.run(
            candidate_profile,
            job_description,
            fit_analysis,
            tailored_draft,
        )

    agent_result = st.session_state.get("agent_workflow_result")
    if agent_result:
        _render_agent_workflow_result(agent_result)
    else:
        st.info(
            "{mode} workflow is ready. Run it to generate profile positioning, fit narrative, tailored wording, and review notes.".format(
                mode=mode_label
            )
        )

    report = build_application_report(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        agent_result=agent_result,
    )
    _render_report_package(report, agent_result=agent_result)
