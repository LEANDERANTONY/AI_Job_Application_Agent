import streamlit as st

from src.config import (
    assisted_workflow_requires_login,
    DEMO_JOB_DESCRIPTION_DIR,
    DEMO_RESUME_DIR,
    list_demo_files,
)
from src.schemas import AgentWorkflowResult, CandidateProfile, FitAnalysis, TailoredResumeDraft
from src.ui.components import render_metric_card, render_section_head
from src.ui.page_artifacts import (
    render_export_bundle_actions as _render_export_bundle_actions,
    render_report_package as _render_report_package,
    render_tailored_resume_artifact as _render_tailored_resume_artifact,
)
from src.ui.page_assistant import render_assistant_panel as _render_assistant_panel
from src.ui.page_history import render_history_page as _render_history_page
from src.ui.state import is_authenticated, set_current_menu
from src.ui.workflow import (
    build_application_report_view_model,
    build_job_workflow_view_model,
    build_tailored_resume_artifact_view_model,
    get_resume_page_state,
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


def _format_remaining_capacity(remaining, limit):
    if limit is None or remaining is None:
        return "Unlimited"
    return str(remaining)


def _render_openai_usage(usage):
    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Browser Session Runs Left",
            _format_remaining_capacity(usage.get("remaining_calls"), usage.get("max_calls")),
            "Estimated assisted runs still available in this browser session.",
        )
    with cols[1]:
        render_metric_card(
            "Browser Session Capacity Left",
            _format_remaining_capacity(
                usage.get("remaining_total_tokens"),
                usage.get("max_total_tokens"),
            ),
            "Remaining assisted capacity in this browser session before the app falls back to the deterministic path.",
        )
    with cols[2]:
        budget_reached = (
            usage.get("remaining_calls") == 0
            or usage.get("remaining_total_tokens") == 0
        )
        render_metric_card(
            "Session Assisted Mode",
            "Limit Reached" if budget_reached else "Available",
            "If this session limit is reached, the workflow remains available in deterministic fallback mode.",
        )

    st.caption(
        "Browser-session safeguards only apply to this session. Daily quota is account-level and is enforced across signed-in sessions."
    )

    last_metadata = usage.get("last_response_metadata") or {}
    if last_metadata:
        st.caption(
            "Latest assisted step used {tokens} tokens and finished with status `{status}`.".format(
                tokens=last_metadata.get("total_tokens", 0),
                status=last_metadata.get("status") or "unknown",
            )
        )


def _render_daily_quota_status(daily_quota):
    if not daily_quota:
        return
    cols = st.columns(4)
    with cols[0]:
        render_metric_card(
            "Daily Workflow Runs Left",
            _format_remaining_capacity(daily_quota.remaining_calls, daily_quota.max_calls),
            "Remaining assisted runs for the current UTC day based on your plan tier.",
        )
    with cols[1]:
        render_metric_card(
            "Daily Capacity Left",
            _format_remaining_capacity(
                daily_quota.remaining_total_tokens,
                daily_quota.max_total_tokens,
            ),
            "Remaining assisted token capacity for the current UTC day.",
        )
    with cols[2]:
        render_metric_card(
            "Plan Tier",
            daily_quota.plan_tier,
            "Daily assisted limits are enforced from persisted authenticated usage.",
        )
    with cols[3]:
        render_metric_card(
            "Quota State",
            "Exhausted" if daily_quota.quota_exhausted else "Available",
            "This is the account-level assisted quota state for the current UTC day.",
        )

    if daily_quota.quota_exhausted:
        st.warning(
            "Your daily assisted limit has been reached. The deterministic workflow remains available, and assisted mode will reset on the next UTC day unless your plan tier changes."
        )
    else:
        st.caption(
            "Daily quota window: {start} to {end} UTC.".format(
                start=daily_quota.window_start,
                end=daily_quota.window_end,
            )
        )


def _render_resume_metrics(resume_document):
    value = resume_document.filetype if resume_document else "Waiting"
    render_metric_card("Resume Status", value, "Resume parsing is deterministic and file-based.")


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
        _render_list("Source Signals", candidate_profile.source_signals, "No source signals available yet.")


def render_resume_page():
    render_section_head("Resume Intake", "Parse an existing resume and keep it ready for tailoring.")
    resume_files = list_demo_files(DEMO_RESUME_DIR, (".pdf", ".docx", ".txt"))
    resume_document, candidate_profile_resume = get_resume_page_state()
    left_col, right_col = st.columns([1.1, 1.2])
    with left_col:
        selected_resume = st.selectbox("Try a sample resume", ["None", *resume_files])
        if selected_resume != "None":
            resume_document, candidate_profile_resume = use_sample_resume(selected_resume)
        uploaded_file = st.file_uploader("Or upload your own resume file", type=["pdf", "docx", "txt"])
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


def _render_fit_snapshot(candidate_profile: CandidateProfile, fit_analysis: FitAnalysis, tailored_draft: TailoredResumeDraft):
    st.markdown("---")
    render_section_head(
        "Readiness Snapshot",
        "Deterministic fit analysis built from the normalized candidate profile and JD.",
    )

    cols = st.columns(3)
    with cols[0]:
        render_metric_card("Fit Score", f"{fit_analysis.overall_score}/100", "Weighted from matched skills and experience signals.")
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
        _render_list("Matched Hard Skills", fit_analysis.matched_hard_skills, "No matched hard-skill evidence yet.")
        _render_list("Strengths", fit_analysis.strengths, "No strengths have been surfaced yet.")
        _render_list("Highlighted Skills For Resume", tailored_draft.highlighted_skills, "No highlighted skills prepared yet.")
    with right_col:
        _render_list("Missing Hard Skills", fit_analysis.missing_hard_skills, "Hard-skill coverage is complete for the extracted JD keywords.")
        _render_list("Gaps", fit_analysis.gaps, "No major gaps surfaced from the current inputs.")
        _render_list("Recommendations", fit_analysis.recommendations, "No recommendations generated yet.")

    with st.expander("Tailored Resume Draft Preview", expanded=True):
        st.markdown("**Professional Summary Draft**")
        st.write(tailored_draft.professional_summary)
        _render_list("Priority Bullets", tailored_draft.priority_bullets, "No priority bullets generated yet.")
        _render_list("Gap Mitigation Steps", tailored_draft.gap_mitigation_steps, "No mitigation steps generated yet.")
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
        render_metric_card("Execution Mode", "OpenAI" if agent_result.mode == "openai" else "Fallback", "Explicit model calls run only on button press.")
    with cols[1]:
        render_metric_card("Review Status", "Approved" if agent_result.review.approved else "Needs Revision", "The review agent is the final quality gate.")
    with cols[2]:
        render_metric_card("Model", agent_result.model, "Fallback means deterministic logic only.")

    with st.expander("Profile and Job Positioning", expanded=True):
        st.markdown("**Profile Positioning Headline**")
        st.write(agent_result.profile.positioning_headline or "No positioning headline produced.")
        _render_list("Evidence Highlights", agent_result.profile.evidence_highlights, "No evidence highlights produced.")
        _render_list("Strengths", agent_result.profile.strengths, "No strengths produced.")
        _render_list("Job Messaging Guidance", agent_result.job.messaging_guidance, "No job messaging guidance produced.")

    left_col, right_col = st.columns(2)
    with left_col:
        _render_list("Fit Summary", [agent_result.fit.fit_summary], "No fit summary produced.")
        _render_list("Top Matches", agent_result.fit.top_matches, "No top matches produced.")
        _render_list("Interview Themes", agent_result.fit.interview_themes, "No interview themes produced.")
    with right_col:
        _render_list("Rewritten Bullet Ideas", agent_result.tailoring.rewritten_bullets, "No rewritten bullets produced.")
        _render_list("Highlighted Skills", agent_result.tailoring.highlighted_skills, "No highlighted skills produced.")
        _render_list("Cover Letter Themes", agent_result.tailoring.cover_letter_themes, "No cover letter themes produced.")

    with st.expander("Application Strategy", expanded=False):
        st.markdown("**Recruiter Positioning**")
        if agent_result.strategy and agent_result.strategy.recruiter_positioning:
            st.write(agent_result.strategy.recruiter_positioning)
        else:
            st.caption("No recruiter positioning produced.")
        _render_list("Cover Letter Talking Points", agent_result.strategy.cover_letter_talking_points if agent_result.strategy else [], "No cover letter talking points produced.")
        _render_list("Interview Preparation Themes", agent_result.strategy.interview_preparation_themes if agent_result.strategy else [], "No interview preparation themes produced.")
        _render_list("Portfolio / Project Emphasis", agent_result.strategy.portfolio_project_emphasis if agent_result.strategy else [], "No portfolio or project emphasis produced.")

    with st.expander("Review Notes", expanded=True):
        st.markdown("**Tailored Professional Summary**")
        st.write(agent_result.tailoring.professional_summary)
        _render_list("Grounding Issues", agent_result.review.grounding_issues, "No grounding issues detected.")
        _render_list("Revision Requests", agent_result.review.revision_requests, "No revisions requested.")
        _render_list("Final Notes", agent_result.review.final_notes, "No final notes produced.")

    if agent_result.review_history:
        with st.expander("Revision Pass History", expanded=False):
            for pass_result in agent_result.review_history:
                status = "Approved" if pass_result.review.approved else "Needs Revision"
                st.markdown("**Pass {index}: {status}**".format(index=pass_result.pass_index, status=status))
                st.write(pass_result.tailoring.professional_summary)
                _render_list("Revision Requests", pass_result.review.revision_requests, "No revisions requested on this pass.")
                _render_list("Grounding Issues", pass_result.review.grounding_issues, "No grounding issues detected on this pass.")
                if pass_result.strategy:
                    _render_list("Interview Preparation Themes", pass_result.strategy.interview_preparation_themes, "No interview themes produced on this pass.")
                st.markdown("---")


def render_history_page():
    return _render_history_page(_render_daily_quota_status)


def render_job_description_page():
    render_section_head("Job Description Intake", "Load a target role and convert it into structured requirements.")
    demo_files = list_demo_files(DEMO_JOB_DESCRIPTION_DIR, (".txt", ".pdf", ".docx"))

    left_col, right_col = st.columns([1.1, 1.2])
    with left_col:
        uploaded_jd = st.file_uploader("Upload Job Description", type=["pdf", "docx", "txt"])
        selected_sample = st.selectbox("Try a sample job description", ["None", *demo_files])
    with right_col:
        pasted_text = st.text_area("Or paste the job description here", height=240)

    jd_text, jd_source = resolve_job_description_input(uploaded_jd=uploaded_jd, selected_sample=selected_sample, pasted_text=pasted_text)

    st.caption(f"JD Source: {jd_source if jd_text else 'None'}")
    workflow_view_model = build_job_workflow_view_model(jd_text, jd_source)
    if not workflow_view_model.job_description:
        return

    job_description = workflow_view_model.job_description

    cols = st.columns(3)
    with cols[0]:
        render_metric_card("Target Role", job_description.title or "Unknown", "Structured title extracted from the JD.")
    with cols[1]:
        render_metric_card("Hard Skills", str(len(job_description.requirements.hard_skills)), "Matched hard-skill keywords.")
    with cols[2]:
        render_metric_card("Soft Skills", str(len(job_description.requirements.soft_skills)), "Matched soft-skill keywords.")

    preview_col, details_col = st.columns([1.1, 1.0])
    with preview_col:
        st.subheader("Cleaned Job Description")
        st.text_area("Cleaned Text", job_description.cleaned_text, height=300, label_visibility="collapsed")
    with details_col:
        st.subheader("Structured Job Details")
        st.markdown(f"- **Job Title:** {job_description.title}")
        st.markdown(f"- **Location:** {job_description.location or 'N/A'}")
        st.markdown("- **Experience Required:** " f"{job_description.requirements.experience_requirement or 'N/A'}")
        st.markdown(f"- **Hard Skills:** {', '.join(job_description.requirements.hard_skills) or 'N/A'}")
        st.markdown(f"- **Soft Skills:** {', '.join(job_description.requirements.soft_skills) or 'N/A'}")
        st.markdown(f"- **Must-Have Signals:** {len(job_description.requirements.must_haves)}")
        st.markdown(f"- **Nice-To-Have Signals:** {len(job_description.requirements.nice_to_haves)}")

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
        st.info("Load a resume first. Once candidate data exists, this page will render a fit snapshot and tailored resume guidance.")
        return

    fit_analysis = workflow_view_model.fit_analysis
    tailored_draft = workflow_view_model.tailored_draft
    _render_fit_snapshot(candidate_profile, fit_analysis, tailored_draft)

    st.markdown("---")
    ai_session = workflow_view_model.ai_session
    st.caption("Run the supervised workflow explicitly to avoid unnecessary model-backed usage on every rerun.")
    st.info("Account quota and browser-session safeguards are separate. Daily quota is shared across signed-in sessions, while the session budget below only applies to this browser session.")
    _render_daily_quota_status(ai_session.daily_quota)
    _render_openai_usage(ai_session.usage)
    if ai_session.budget_reached and ai_session.openai_service.is_available():
        st.warning("The session usage limit has been reached. Running the supervised workflow now will stay in deterministic fallback mode until the session resets or the limit is raised.")
    login_required = assisted_workflow_requires_login() and not is_authenticated()
    if login_required:
        st.info("Sign in with Google from the sidebar to run the AI-assisted workflow and keep usage tied to your account.")
    if st.button("Run supervised agent workflow", key="run_supervised_workflow", disabled=login_required):
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
    _render_assistant_panel("Manual JD Input", workflow_view_model=workflow_view_model, artifact=tailored_resume_artifact, report=report)