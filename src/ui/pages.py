from html import escape

import streamlit as st

from src.config import (
    assisted_workflow_requires_login,
)
from src.errors import InputValidationError
from src.schemas import AgentWorkflowResult, CandidateProfile, FitAnalysis, TailoredResumeDraft
from src.ui.components import render_metric_card, render_page_divider, render_section_head
from src.ui.page_artifacts import (
    render_cover_letter_artifact as _render_cover_letter_artifact,
    render_report_package as _render_report_package,
    render_tailored_resume_artifact as _render_tailored_resume_artifact,
)
from src.ui.state import (
    is_authenticated,
    request_menu_navigation,
)
from src.ui.workflow import (
    build_application_report_view_model,
    build_cover_letter_artifact_view_model,
    build_job_workflow_view_model,
    build_tailored_resume_artifact_view_model,
    get_resume_page_state,
    resolve_job_description_input,
    run_supervised_workflow,
    use_uploaded_resume,
)


def _go_to(menu_name):
    request_menu_navigation(menu_name)
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


def _simplify_model_name(model_name):
    if not model_name:
        return "Unknown"

    replacements = {
        "gpt-5-mini-2025-08-07": "GPT-5 Mini",
        "gpt-5.4": "GPT-5.4",
        "gpt-5": "GPT-5",
    }

    def normalize_single(value):
        cleaned = value.strip()
        if "[" in cleaned:
            cleaned = cleaned.split("[", 1)[0].strip()
        return replacements.get(cleaned, cleaned)

    cleaned_name = model_name.strip()
    if cleaned_name.startswith("routed(") and cleaned_name.endswith(")"):
        routed_values = cleaned_name[len("routed("):-1]
        normalized = []
        seen = set()
        for part in routed_values.split(","):
            simplified = normalize_single(part)
            if simplified and simplified not in seen:
                normalized.append(simplified)
                seen.add(simplified)
        return "Routed: {names}".format(names=", ".join(normalized)) if normalized else "Routed"

    return normalize_single(cleaned_name)


def _review_status_label(review):
    if not review:
        return "Unknown"
    if review.approved and (getattr(review, "corrected_tailoring", None) or getattr(review, "corrected_strategy", None)):
        return "Approved After Corrections"
    if review.approved:
        return "Approved"
    return "Needs Revision"


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
            "Your daily assisted limit has been reached. The backup workflow remains available, and assisted mode will reset on the next UTC day unless your plan tier changes."
        )
    else:
        st.caption(
            "Daily quota window: {start} to {end} UTC.".format(
                start=daily_quota.window_start,
                end=daily_quota.window_end,
            )
        )


def _render_profile_snapshot(candidate_profile: CandidateProfile):
    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Profile Source",
            candidate_profile.source or "Unknown",
            "Profile data currently comes from the resume workflow.",
            slim=True,
        )
    with cols[1]:
        render_metric_card(
            "Skills Available",
            str(len(candidate_profile.skills)),
            "Detected or imported skills available for matching.",
            slim=True,
        )
    with cols[2]:
        render_metric_card(
            "Experience Entries",
            str(len(candidate_profile.experience)),
            "Structured experience depends on what the current resume exposes.",
            slim=True,
        )

    with st.expander("Normalized Candidate Snapshot", expanded=False):
        st.markdown(f"- **Name:** {candidate_profile.full_name or 'Not inferred yet'}")
        st.markdown(f"- **Location:** {candidate_profile.location or 'Not inferred yet'}")
        st.markdown(
            f"- **Skills:** {', '.join(candidate_profile.skills[:8]) or 'No explicit skills detected'}"
        )
        _render_list("Source Signals", candidate_profile.source_signals, "No source signals available yet.")


def render_resume_page():
    render_page_divider()
    render_section_head("Resume Intake", "Sign in first, then upload your resume to start the AI-assisted workflow.")

    if not is_authenticated():
        st.file_uploader(
            "Upload your resume file",
            type=["pdf", "docx", "txt"],
            disabled=True,
        )
        return

    resume_document, candidate_profile_resume = get_resume_page_state()
    uploaded_file = st.file_uploader("Upload your resume file", type=["pdf", "docx", "txt"])
    if uploaded_file is not None:
        resume_document, candidate_profile_resume = use_uploaded_resume(uploaded_file)
    if resume_document:
        st.success(f"{resume_document.filetype} resume parsed successfully.")
        _render_profile_snapshot(candidate_profile_resume)
        if st.button("I have a job description"):
            _go_to("Manual JD Input")


def render_job_search_page():
    render_page_divider()
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
def _render_agent_workflow_result(agent_result: AgentWorkflowResult):
    st.markdown("---")
    render_section_head(
        "Agentic Workflow",
        "AI-assisted analysis turns the parsed inputs into grounded, recruiter-facing guidance.",
    )

    if agent_result.mode != "openai":
        if agent_result.attempted_assisted:
            st.warning(
                "This run started in AI-assisted mode but continued in backup mode. Reason: {reason}".format(
                    reason=agent_result.fallback_reason or "The AI-assisted step did not complete successfully."
                )
            )
        else:
            st.info(
                "This run used the backup workflow because AI-assisted execution was not available for this run."
            )

    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Execution Mode",
            "OpenAI" if agent_result.mode == "openai" else ("Fallback After AI Attempt" if agent_result.attempted_assisted else "Fallback"),
            "Explicit model calls run only on button press.",
            slim=True,
        )
    with cols[1]:
        render_metric_card("Review Status", _review_status_label(agent_result.review), "The review agent is the final quality gate on the final corrected output.", slim=True)
    with cols[2]:
        render_metric_card("Model", _simplify_model_name(agent_result.model), "Backup mode runs without model calls.", slim=True)

    if agent_result.fallback_details:
        with st.expander("Fallback Details", expanded=False):
            st.code(agent_result.fallback_details)

    with st.expander("Application Strategy", expanded=False):
        st.markdown("**Recruiter Positioning**")
        if agent_result.strategy and agent_result.strategy.recruiter_positioning:
            st.write(agent_result.strategy.recruiter_positioning)
        else:
            st.caption("No recruiter positioning produced.")
        _render_list("Cover Letter Talking Points", agent_result.strategy.cover_letter_talking_points if agent_result.strategy else [], "No cover letter talking points produced.")
        _render_list("Portfolio / Project Emphasis", agent_result.strategy.portfolio_project_emphasis if agent_result.strategy else [], "No portfolio or project emphasis produced.")


def _workflow_progress_palette(title):
    palette = {
        "Workflow crew": {
            "accent": "#2563eb",
            "surface": "linear-gradient(135deg, rgba(255,255,255,0.98), rgba(239,246,255,0.96))",
            "tag_background": "rgba(37, 99, 235, 0.10)",
            "tag_text": "#1d4ed8",
        },
        "Backup workflow": {
            "accent": "#475569",
            "surface": "linear-gradient(135deg, rgba(255,255,255,0.98), rgba(248,250,252,0.96))",
            "tag_background": "rgba(71, 85, 105, 0.10)",
            "tag_text": "#334155",
        },
        "Scout agent": {
            "accent": "#0f766e",
            "surface": "linear-gradient(135deg, rgba(255,255,255,0.98), rgba(240,253,250,0.96))",
            "tag_background": "rgba(15, 118, 110, 0.10)",
            "tag_text": "#0f766e",
        },
        "Signal agent": {
            "accent": "#2563eb",
            "surface": "linear-gradient(135deg, rgba(255,255,255,0.98), rgba(239,246,255,0.96))",
            "tag_background": "rgba(37, 99, 235, 0.10)",
            "tag_text": "#1d4ed8",
        },
        "Matchmaker agent": {
            "accent": "#1d4ed8",
            "surface": "linear-gradient(135deg, rgba(255,255,255,0.98), rgba(239,246,255,0.96))",
            "tag_background": "rgba(29, 78, 216, 0.10)",
            "tag_text": "#1d4ed8",
        },
        "Forge agent": {
            "accent": "#ea580c",
            "surface": "linear-gradient(135deg, rgba(255,255,255,0.98), rgba(255,247,237,0.96))",
            "tag_background": "rgba(234, 88, 12, 0.10)",
            "tag_text": "#c2410c",
        },
        "Navigator agent": {
            "accent": "#0284c7",
            "surface": "linear-gradient(135deg, rgba(255,255,255,0.98), rgba(240,249,255,0.96))",
            "tag_background": "rgba(2, 132, 199, 0.10)",
            "tag_text": "#0369a1",
        },
        "Gatekeeper agent": {
            "accent": "#b45309",
            "surface": "linear-gradient(135deg, rgba(255,255,255,0.98), rgba(255,251,235,0.96))",
            "tag_background": "rgba(180, 83, 9, 0.10)",
            "tag_text": "#92400e",
        },
        "Builder agent": {
            "accent": "#2563eb",
            "surface": "linear-gradient(135deg, rgba(255,255,255,0.98), rgba(239,246,255,0.96))",
            "tag_background": "rgba(37, 99, 235, 0.10)",
            "tag_text": "#1d4ed8",
        },
        "Cover letter agent": {
            "accent": "#7c3aed",
            "surface": "linear-gradient(135deg, rgba(255,255,255,0.98), rgba(245,243,255,0.96))",
            "tag_background": "rgba(124, 58, 237, 0.10)",
            "tag_text": "#6d28d9",
        },
    }
    return palette.get(
        title,
        {
            "accent": "#2563eb",
            "surface": "linear-gradient(135deg, rgba(255,255,255,0.98), rgba(239,246,255,0.96))",
            "tag_background": "rgba(37, 99, 235, 0.10)",
            "tag_text": "#1d4ed8",
        },
    )


def _run_supervised_workflow_with_progress(workflow_view_model):
    status_placeholder = st.empty()
    progress_bar = st.progress(0)
    latest_progress = {"value": 0}

    def update_progress(title, detail, value):
        clamped_value = max(latest_progress["value"], max(0, min(100, int(value))))
        latest_progress["value"] = clamped_value
        palette = _workflow_progress_palette(title)
        status_placeholder.markdown(
            """
            <div style="position:relative; overflow:hidden; border:1px solid rgba(20, 32, 51, 0.12); border-radius:18px; background:{surface}; padding:0.95rem 1rem 0.95rem 1.05rem; margin:0 0 0.65rem 0; box-shadow:0 16px 34px rgba(0, 0, 0, 0.14);">
                <div style="position:absolute; left:0; top:0; bottom:0; width:4px; background:{accent};"></div>
                <div style="display:inline-flex; align-items:center; border-radius:999px; padding:0.25rem 0.55rem; background:{tag_background}; color:{tag_text}; font-size:0.74rem; font-weight:700; letter-spacing:0.08em; text-transform:uppercase; margin-bottom:0.45rem;">{title}</div>
                <div style="font-size:0.97rem; line-height:1.45; color:var(--ink);">{detail}</div>
            </div>
            """.format(
                title=escape(title),
                detail=escape(detail),
                surface=palette["surface"],
                accent=palette["accent"],
                tag_background=palette["tag_background"],
                tag_text=palette["tag_text"],
            ),
            unsafe_allow_html=True,
        )
        progress_bar.progress(clamped_value)

    try:
        workflow_view_model = run_supervised_workflow(
            workflow_view_model,
            progress_callback=update_progress,
        )
    except InputValidationError as error:
        status_placeholder.empty()
        progress_bar.empty()
        st.error(str(error))
        return workflow_view_model
    except Exception:
        status_placeholder.empty()
        progress_bar.empty()
        raise

    status_placeholder.empty()
    progress_bar.empty()
    return workflow_view_model

def render_job_description_page():
    render_page_divider()
    render_section_head("Job Description Intake", "Load a target role and convert it into structured requirements.")
    uploaded_jd = st.file_uploader("Upload Job Description", type=["pdf", "docx", "txt"])
    st.markdown(
        """
        <div class="intake-divider" aria-hidden="true">
            <span>OR</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    pasted_text = st.text_area("Paste the job description here", height=180, key="manual_jd_paste")

    jd_text, jd_source = resolve_job_description_input(
        uploaded_jd=uploaded_jd,
        selected_sample="None",
        pasted_text=pasted_text,
    )

    st.caption(f"JD Source: {jd_source if jd_text else 'None'}")
    st.markdown("---")
    workflow_view_model = build_job_workflow_view_model(jd_text, jd_source)
    if not workflow_view_model.job_description:
        return

    job_description = workflow_view_model.job_description

    cols = st.columns(3)
    with cols[0]:
        render_metric_card("Target Role", job_description.title or "Unknown", "Structured title extracted from the JD.", dense=True, slim=True)
    with cols[1]:
        render_metric_card("Hard Skills", str(len(job_description.requirements.hard_skills)), "Matched hard-skill keywords.", dense=True, slim=True)
    with cols[2]:
        render_metric_card("Soft Skills", str(len(job_description.requirements.soft_skills)), "Matched soft-skill keywords.", dense=True, slim=True)

    candidate_profile = workflow_view_model.candidate_profile
    if not candidate_profile:
        st.info("Load a resume first. Once candidate data exists, this page will render a fit snapshot and tailored resume guidance.")
        return

    ai_session = workflow_view_model.ai_session
    st.caption("Run the AI-assisted analysis explicitly to avoid unnecessary model-backed usage on every rerun.")
    login_required = assisted_workflow_requires_login() and not is_authenticated()
    if login_required:
        st.info("Sign in with Google from the sidebar to run the AI-assisted analysis and keep usage tied to your account.")
    if st.button("Run Agentic Analysis", key="run_supervised_workflow", disabled=login_required):
        workflow_view_model = _run_supervised_workflow_with_progress(workflow_view_model)
        if workflow_view_model.agent_result:
            st.rerun()

    agent_result = workflow_view_model.agent_result
    if agent_result:
        _render_agent_workflow_result(agent_result)
    else:
        st.info(
            "{mode} analysis is ready. Run it to generate findings, application strategy guidance, and tailored output support.".format(
                mode=ai_session.mode_label
            )
        )

    tailored_resume_artifact = build_tailored_resume_artifact_view_model(workflow_view_model)
    _render_tailored_resume_artifact(tailored_resume_artifact, agent_result=agent_result)

    cover_letter_artifact = build_cover_letter_artifact_view_model(workflow_view_model)
    _render_cover_letter_artifact(cover_letter_artifact, agent_result=agent_result)

    report = build_application_report_view_model(workflow_view_model)
    _render_report_package(report, agent_result=agent_result)
