import streamlit as st

from src.assistant_service import AssistantService
from src.config import (
    DEMO_JOB_DESCRIPTION_DIR,
    DEMO_RESUME_DIR,
    list_demo_files,
)
from src.errors import ExportError
from src.exporters import export_markdown_bytes
from src.resume_diff import build_resume_diff, build_resume_diff_metrics
from src.resume_builder import RESUME_THEMES
from src.schemas import (
    AgentWorkflowResult,
    AssistantTurn,
    ApplicationReport,
    CandidateProfile,
    FitAnalysis,
    TailoredResumeArtifact,
    TailoredResumeDraft,
)
from src.ui.components import render_metric_card, render_section_head
from src.ui.state import (
    TAILORED_RESUME_THEME,
    append_assistant_turn,
    clear_assistant_history,
    get_assistant_history,
    set_current_menu,
)
from src.ui.workflow import (
    build_application_report_view_model,
    build_tailored_resume_artifact_view_model,
    build_job_workflow_view_model,
    get_cached_export_bundle_package,
    get_active_candidate_profile,
    get_cached_pdf_package,
    get_cached_tailored_resume_pdf_package,
    get_resume_page_state,
    prepare_pdf_package,
    prepare_export_bundle_package,
    prepare_tailored_resume_pdf_package,
    resolve_job_description_input,
    run_supervised_workflow,
    use_sample_resume,
    use_uploaded_resume,
)


def _go_to(menu_name):
    set_current_menu(menu_name)
    st.rerun()


def _render_list(title, items, empty_state):
    st.markdown(f"**{title}**")
    if items:
        for item in items:
            st.markdown(f"- {item}")
    else:
        st.caption(empty_state)


def _format_usage_ratio(used, limit):
    if limit is None:
        return str(used)
    return "{used}/{limit}".format(used=used, limit=limit)


def _format_remaining_capacity(remaining, limit):
    if limit is None or remaining is None:
        return "Unlimited"
    return str(remaining)


def _render_openai_usage(usage):
    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Workflow Runs Left",
            _format_remaining_capacity(
                usage.get("remaining_calls"),
                usage.get("max_calls"),
            ),
            "Estimated assisted runs still available in this browser session.",
        )
    with cols[1]:
        render_metric_card(
            "Session Capacity Left",
            _format_remaining_capacity(
                usage.get("remaining_total_tokens"),
                usage.get("max_total_tokens"),
            ),
            "Remaining assisted capacity before the app falls back to the deterministic path.",
        )
    with cols[2]:
        budget_reached = (
            usage.get("remaining_calls") == 0
            or usage.get("remaining_total_tokens") == 0
        )
        render_metric_card(
            "Assisted Mode",
            "Limit Reached" if budget_reached else "Available",
            "If the limit is reached, the workflow remains available in the deterministic fallback mode.",
        )

    last_metadata = usage.get("last_response_metadata") or {}
    if last_metadata:
        st.caption(
            "Latest assisted step used {tokens} tokens and finished with status `{status}`.".format(
                tokens=last_metadata.get("total_tokens", 0),
                status=last_metadata.get("status") or "unknown",
            )
        )


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
            "Profile data currently comes from the resume workflow.",
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
            "Structured experience depends on what the current resume exposes.",
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
    resume_document, candidate_profile_resume = get_resume_page_state()
    left_col, right_col = st.columns([1.1, 1.2])
    with left_col:
        selected_resume = st.selectbox("Try a sample resume", ["None", *resume_files])
        if selected_resume != "None":
            resume_document, candidate_profile_resume = use_sample_resume(selected_resume)
        uploaded_file = st.file_uploader(
            "Or upload your own resume file",
            type=["pdf", "docx", "txt"],
        )
        if uploaded_file is not None:
            resume_document, candidate_profile_resume = use_uploaded_resume(uploaded_file)
    with right_col:
        _render_resume_metrics(resume_document)
    if resume_document:
        st.success(f"{resume_document.filetype} resume parsed successfully.")
        _render_profile_snapshot(candidate_profile_resume)
        st.text_area("Extracted Resume Text", resume_document.text, height=320)
        if st.button("I have a job description"):
            _go_to("Manual JD Input")
    _render_assistant_panel("Upload Resume")


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
    _render_assistant_panel("Job Search")


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

    with st.expander("Application Strategy", expanded=False):
        st.markdown("**Recruiter Positioning**")
        if agent_result.strategy and agent_result.strategy.recruiter_positioning:
            st.write(agent_result.strategy.recruiter_positioning)
        else:
            st.caption("No recruiter positioning produced.")
        _render_list(
            "Cover Letter Talking Points",
            agent_result.strategy.cover_letter_talking_points if agent_result.strategy else [],
            "No cover letter talking points produced.",
        )
        _render_list(
            "Interview Preparation Themes",
            agent_result.strategy.interview_preparation_themes if agent_result.strategy else [],
            "No interview preparation themes produced.",
        )
        _render_list(
            "Portfolio / Project Emphasis",
            agent_result.strategy.portfolio_project_emphasis if agent_result.strategy else [],
            "No portfolio or project emphasis produced.",
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

    if agent_result.review_history:
        with st.expander("Revision Pass History", expanded=False):
            for pass_result in agent_result.review_history:
                status = "Approved" if pass_result.review.approved else "Needs Revision"
                st.markdown(
                    "**Pass {index}: {status}**".format(
                        index=pass_result.pass_index,
                        status=status,
                    )
                )
                st.write(pass_result.tailoring.professional_summary)
                _render_list(
                    "Revision Requests",
                    pass_result.review.revision_requests,
                    "No revisions requested on this pass.",
                )
                _render_list(
                    "Grounding Issues",
                    pass_result.review.grounding_issues,
                    "No grounding issues detected on this pass.",
                )
                if pass_result.strategy:
                    _render_list(
                        "Interview Preparation Themes",
                        pass_result.strategy.interview_preparation_themes,
                        "No interview themes produced on this pass.",
                    )
                st.markdown("---")


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
        if get_cached_pdf_package() is None:
            if st.button("Prepare PDF Package", key="prepare_pdf_package"):
                try:
                    with st.spinner("Generating PDF package..."):
                        prepare_pdf_package(report)
                except ExportError as error:
                    st.warning(error.user_message)
        else:
            st.download_button(
                "Download PDF Package",
                data=get_cached_pdf_package(),
                file_name=report.filename_stem + ".pdf",
                mime="application/pdf",
                key="download_pdf_package",
            )


def _render_export_bundle_actions(
    artifact: TailoredResumeArtifact,
    report: ApplicationReport,
):
    st.markdown("---")
    render_section_head(
        "Combined Export",
        "Download the tailored resume and strategy report together in one bundle.",
    )

    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Resume Only",
            "Available",
            "Use the tailored resume section if you only want the generated resume artifact.",
        )
    with cols[1]:
        render_metric_card(
            "Report Only",
            "Available",
            "Use the application package section if you only want the report artifact.",
        )
    with cols[2]:
        render_metric_card(
            "Both Together",
            "ZIP Bundle",
            "Generates one archive containing markdown and PDF versions of both outputs.",
        )

    cached_bundle = get_cached_export_bundle_package()
    if cached_bundle is None:
        if st.button("Prepare Combined Export Bundle", key="prepare_export_bundle"):
            try:
                with st.spinner("Preparing report and tailored resume bundle..."):
                    prepare_export_bundle_package(report, artifact)
            except ExportError as error:
                st.warning(error.user_message)
    else:
        bundle_name = "{name}.zip".format(
            name=artifact.filename_stem.replace("-tailored-resume", "-application-bundle")
        )
        st.download_button(
            "Download Combined Export Bundle",
            data=cached_bundle,
            file_name=bundle_name,
            mime="application/zip",
            key="download_export_bundle",
        )


def _render_assistant_panel(current_page, workflow_view_model=None, artifact=None, report=None):
    st.markdown("---")
    render_section_head(
        "Ask The Assistant",
        "Use product help for navigation questions or ask grounded questions about the current resume and report.",
    )

    mode_options = ["product_help"]
    if workflow_view_model and workflow_view_model.candidate_profile and workflow_view_model.job_description:
        mode_options.append("application_qa")

    page_slug = current_page.lower().replace(" ", "_")
    mode_labels = {
        "product_help": "Using the App",
        "application_qa": "About My Resume",
    }
    mode = st.radio(
        "Assistant Mode",
        mode_options,
        horizontal=True,
        key="assistant_mode_{page}".format(page=page_slug),
        format_func=lambda value: mode_labels[value],
    )

    history = get_assistant_history(mode)
    for turn in history:
        with st.chat_message("user"):
            st.write(turn.question)
        with st.chat_message("assistant"):
            st.write(turn.response.answer)
            if turn.response.sources:
                st.caption("Sources: " + ", ".join(turn.response.sources))

    question = st.text_input(
        "Ask a question",
        key="assistant_question_{page}_{mode}".format(page=page_slug, mode=mode),
        placeholder=(
            "Ask how to use the app..."
            if mode == "product_help"
            else "Ask about your resume, JD, or report..."
        ),
    )
    ask_col, clear_col = st.columns(2)
    with ask_col:
        ask_clicked = st.button(
            "Ask Assistant",
            key="ask_assistant_{page}_{mode}".format(page=page_slug, mode=mode),
        )
    with clear_col:
        clear_clicked = st.button(
            "Clear Chat",
            key="clear_assistant_{page}_{mode}".format(page=page_slug, mode=mode),
        )

    if clear_clicked:
        clear_assistant_history(mode)
        st.rerun()

    if ask_clicked and question.strip():
        openai_service = None
        if workflow_view_model and workflow_view_model.ai_session:
            openai_service = workflow_view_model.ai_session.openai_service
        assistant = AssistantService(openai_service=openai_service)
        if mode == "product_help":
            response = assistant.answer_product_help(
                question,
                current_page=current_page,
                history=history,
                app_context={
                    "available_pages": ["Upload Resume", "Job Search", "Manual JD Input"],
                    "has_resume": bool(workflow_view_model and workflow_view_model.candidate_profile),
                    "has_job_description": bool(workflow_view_model and workflow_view_model.job_description),
                    "has_tailored_resume": bool(artifact),
                    "has_report": bool(report),
                },
            )
        else:
            response = assistant.answer_application_qa(
                question,
                workflow_view_model,
                report=report,
                artifact=artifact,
                history=history,
            )
        append_assistant_turn(
            mode,
            AssistantTurn(mode=mode, question=question.strip(), response=response),
        )
        st.rerun()


def _render_tailored_resume_artifact(artifact: TailoredResumeArtifact, agent_result: AgentWorkflowResult = None):
    st.markdown("---")
    render_section_head(
        "Tailored Resume Draft",
        "A grounded, JD-aligned resume artifact the candidate can use directly or refine manually.",
    )

    theme_options = list(RESUME_THEMES.keys())
    selected_theme = st.selectbox(
        "Resume Template",
        theme_options,
        index=theme_options.index(artifact.theme) if artifact.theme in theme_options else 0,
        key=TAILORED_RESUME_THEME,
        format_func=lambda value: RESUME_THEMES[value]["label"],
    )
    if selected_theme != artifact.theme:
        st.rerun()

    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Resume Mode",
            "Agent-Enhanced" if agent_result else "Deterministic",
            "Uses the current workflow outputs to generate a recruiter-facing tailored resume draft.",
        )
    with cols[1]:
        render_metric_card(
            "Template",
            RESUME_THEMES.get(artifact.theme, {"label": artifact.theme})["label"],
            RESUME_THEMES.get(artifact.theme, {"tagline": "Theme controls the deterministic layout and section rhythm of the export."})["tagline"],
        )
    with cols[2]:
        render_metric_card(
            "Validation Notes",
            str(len(artifact.validation_notes)),
            artifact.summary,
        )

    left_col, right_col = st.columns(2)
    with left_col:
        _render_list(
            "Change Summary",
            artifact.change_log,
            "No change summary available.",
        )
    with right_col:
        _render_list(
            "Validation Notes",
            artifact.validation_notes,
            "No validation notes available.",
        )

    original_resume_text = artifact.header.full_name and artifact.header.full_name or ""
    original_resume_text = get_active_candidate_profile().resume_text if get_active_candidate_profile() else ""
    diff_metrics = build_resume_diff_metrics(original_resume_text, artifact.markdown)

    metric_cols = st.columns(4)
    with metric_cols[0]:
        render_metric_card(
            "Original Lines",
            str(diff_metrics["original_line_count"]),
            "Line count from the current parsed resume text.",
        )
    with metric_cols[1]:
        render_metric_card(
            "Tailored Lines",
            str(diff_metrics["tailored_line_count"]),
            "Line count in the generated tailored resume artifact.",
        )
    with metric_cols[2]:
        render_metric_card(
            "Added / Removed",
            "{added}/{removed}".format(
                added=diff_metrics["added_lines"],
                removed=diff_metrics["removed_lines"],
            ),
            "Simple diff count to show how much content shifted.",
        )
    with metric_cols[3]:
        render_metric_card(
            "Similarity",
            "{ratio}%".format(ratio=diff_metrics["similarity_ratio"]),
            "Text-level similarity between the original input and tailored output.",
        )

    with st.expander("Preview Tailored Resume", expanded=True):
        st.text_area(
            "Tailored Resume Preview",
            artifact.markdown,
            height=420,
            label_visibility="collapsed",
        )

    with st.expander("Compare Original vs Tailored Resume", expanded=False):
        original_col, tailored_col = st.columns(2)
        with original_col:
            st.markdown("**Original Resume Text**")
            st.text_area(
                "Original Resume Text",
                original_resume_text,
                height=360,
                label_visibility="collapsed",
            )
        with tailored_col:
            st.markdown("**Tailored Resume Text**")
            st.text_area(
                "Tailored Resume Text",
                artifact.markdown,
                height=360,
                label_visibility="collapsed",
            )
        st.markdown("**Unified Diff**")
        st.code(build_resume_diff(original_resume_text, artifact.markdown), language="diff")

    download_col, pdf_col = st.columns(2)
    with download_col:
        st.download_button(
            "Download Tailored Resume Markdown",
            data=export_markdown_bytes(artifact),
            file_name=artifact.filename_stem + ".md",
            mime="text/markdown",
            key="download_tailored_resume_markdown",
        )
    with pdf_col:
        if get_cached_tailored_resume_pdf_package() is None:
            if st.button("Prepare Tailored Resume PDF", key="prepare_tailored_resume_pdf"):
                try:
                    with st.spinner("Generating tailored resume PDF..."):
                        prepare_tailored_resume_pdf_package(artifact)
                except ExportError as error:
                    st.warning(error.user_message)
        else:
            st.download_button(
                "Download Tailored Resume PDF",
                data=get_cached_tailored_resume_pdf_package(),
                file_name=artifact.filename_stem + ".pdf",
                mime="application/pdf",
                key="download_tailored_resume_pdf",
            )


def render_job_description_page():
    render_section_head(
        "Job Description Intake",
        "Load a target role and convert it into structured requirements.",
    )
    demo_files = list_demo_files(DEMO_JOB_DESCRIPTION_DIR, (".txt", ".pdf", ".docx"))

    left_col, right_col = st.columns([1.1, 1.2])
    with left_col:
        uploaded_jd = st.file_uploader("Upload Job Description", type=["pdf", "docx", "txt"])
        selected_sample = st.selectbox("Try a sample job description", ["None", *demo_files])
    with right_col:
        pasted_text = st.text_area("Or paste the job description here", height=240)

    jd_text, jd_source = resolve_job_description_input(
        uploaded_jd=uploaded_jd,
        selected_sample=selected_sample,
        pasted_text=pasted_text,
    )

    st.caption(f"JD Source: {jd_source if jd_text else 'None'}")
    workflow_view_model = build_job_workflow_view_model(jd_text, jd_source)
    if not workflow_view_model.job_description:
        return

    job_description = workflow_view_model.job_description

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
                agents will compare against your resume-derived candidate profile.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    candidate_profile = workflow_view_model.candidate_profile
    if not candidate_profile:
        st.info(
            "Load a resume first. Once candidate data exists, this page will render a fit snapshot and tailored resume guidance."
        )
        return

    fit_analysis = workflow_view_model.fit_analysis
    tailored_draft = workflow_view_model.tailored_draft
    _render_fit_snapshot(candidate_profile, fit_analysis, tailored_draft)

    st.markdown("---")
    ai_session = workflow_view_model.ai_session
    st.caption(
        "Run the supervised workflow explicitly to avoid unnecessary model-backed usage on every rerun."
    )
    _render_openai_usage(ai_session.usage)
    if ai_session.budget_reached and ai_session.openai_service.is_available():
        st.warning(
            "The session usage limit has been reached. Running the supervised workflow now will stay in deterministic fallback mode until the session resets or the limit is raised."
        )
    if st.button("Run supervised agent workflow", key="run_supervised_workflow"):
        workflow_view_model = run_supervised_workflow(workflow_view_model)

    agent_result = workflow_view_model.agent_result
    if agent_result:
        _render_agent_workflow_result(agent_result)
    else:
        st.info(
            "{mode} workflow is ready. Run it to generate profile positioning, fit narrative, application strategy guidance, tailored wording, and review notes.".format(
                mode=ai_session.mode_label
            )
        )

    tailored_resume_artifact = build_tailored_resume_artifact_view_model(workflow_view_model)
    _render_tailored_resume_artifact(tailored_resume_artifact, agent_result=agent_result)

    report = build_application_report_view_model(workflow_view_model)
    _render_report_package(report, agent_result=agent_result)
    _render_export_bundle_actions(tailored_resume_artifact, report)
    _render_assistant_panel(
        "Manual JD Input",
        workflow_view_model=workflow_view_model,
        artifact=tailored_resume_artifact,
        report=report,
    )
