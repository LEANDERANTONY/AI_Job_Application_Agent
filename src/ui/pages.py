from html import escape

import streamlit as st

from src.config import (
    assisted_workflow_requires_login,
    DEMO_JOB_DESCRIPTION_DIR,
    DEMO_RESUME_DIR,
    list_demo_files,
)
from src.errors import InputValidationError
from src.schemas import AgentWorkflowResult, CandidateProfile, FitAnalysis, TailoredResumeDraft
from src.ui.components import render_metric_card, render_section_head
from src.ui.page_artifacts import (
    render_export_bundle_actions as _render_export_bundle_actions,
    render_report_package as _render_report_package,
    render_tailored_resume_artifact as _render_tailored_resume_artifact,
)
from src.ui.page_history import render_history_page as _render_history_page
from src.ui.state import (
    is_authenticated,
    request_menu_navigation,
)
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
        detail_parts = [
            "Latest assisted step used {tokens} tokens and finished with status `{status}`.".format(
                tokens=last_metadata.get("total_tokens", 0),
                status=last_metadata.get("status") or "unknown",
            )
        ]
        estimated_input_chars = last_metadata.get("estimated_input_chars")
        if estimated_input_chars:
            detail_parts.append(
                "Estimated prompt size was {chars} characters.".format(
                    chars=estimated_input_chars
                )
            )
        compacted_sections = last_metadata.get("compacted_sections")
        if compacted_sections not in (None, "", 0, "0"):
            detail_parts.append(
                "Compaction was applied to {count} section(s).".format(
                    count=compacted_sections
                )
            )
        st.caption(" ".join(detail_parts))


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
def _render_fit_snapshot(candidate_profile: CandidateProfile, fit_analysis: FitAnalysis, tailored_draft: TailoredResumeDraft):
    st.markdown("---")
    summary_html = escape(
        tailored_draft.professional_summary or "No professional summary drafted yet."
    )
    bullet_items = [
        "<li>{item}</li>".format(item=escape(item))
        for item in tailored_draft.priority_bullets
        if item
    ]
    mitigation_items = [
        "<li>{item}</li>".format(item=escape(item))
        for item in tailored_draft.gap_mitigation_steps
        if item
    ]
    if not bullet_items:
        bullet_items = ["<li>No priority bullets generated yet.</li>"]
    if not mitigation_items:
        mitigation_items = ["<li>No mitigation steps generated yet.</li>"]

    st.markdown(
        """
        <div class="deterministic-draft-card">
            <div class="deterministic-draft-kicker">Deterministic Baseline</div>
            <h3>Tailored Resume Draft Preview</h3>
            <p class="deterministic-draft-copy">
                This is the grounded pre-agent draft built directly from the parsed resume and JD. It stays visible as a clean baseline without the full deterministic fit breakdown.
            </p>
            <div class="deterministic-draft-section">
                <h4>Professional Summary Draft</h4>
                <p>{summary}</p>
            </div>
            <div class="deterministic-draft-grid">
                <div class="deterministic-draft-section">
                    <h4>Priority Bullets</h4>
                    <ul>{bullets}</ul>
                </div>
                <div class="deterministic-draft-section">
                    <h4>Gap Mitigation Steps</h4>
                    <ul>{mitigations}</ul>
                </div>
            </div>
        </div>
        """.format(
            summary=summary_html,
            bullets="".join(bullet_items),
            mitigations="".join(mitigation_items),
        ),
        unsafe_allow_html=True,
    )


def _render_agent_workflow_result(agent_result: AgentWorkflowResult):
    st.markdown("---")
    render_section_head(
        "Supervised Agent Workflow",
        "Specialist agents refine the deterministic baseline while preserving grounded output.",
    )

    if agent_result.mode != "openai":
        if agent_result.attempted_assisted:
            st.warning(
                "This run started in AI-assisted mode but downgraded to deterministic fallback. Reason: {reason}".format(
                    reason=agent_result.fallback_reason or "The AI-assisted step did not complete successfully."
                )
            )
        else:
            st.info(
                "This run used deterministic fallback because AI-assisted execution was not available for this run."
            )

    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Execution Mode",
            "OpenAI" if agent_result.mode == "openai" else ("Fallback After AI Attempt" if agent_result.attempted_assisted else "Fallback"),
            "Explicit model calls run only on button press.",
        )
    with cols[1]:
        render_metric_card("Review Status", "Approved" if agent_result.review.approved else "Needs Revision", "The review agent is the final quality gate.")
    with cols[2]:
        render_metric_card("Model", agent_result.model, "Fallback means deterministic logic only.")

    if agent_result.fallback_details:
        with st.expander("Fallback Details", expanded=False):
            st.code(agent_result.fallback_details)

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

    ai_session = workflow_view_model.ai_session
    fit_analysis = workflow_view_model.fit_analysis
    tailored_draft = workflow_view_model.tailored_draft
    _render_fit_snapshot(candidate_profile, fit_analysis, tailored_draft)

    st.markdown("---")
    st.caption("Run the supervised workflow explicitly to avoid unnecessary model-backed usage on every rerun.")
    login_required = assisted_workflow_requires_login() and not is_authenticated()
    if login_required:
        st.info("Sign in with Google from the sidebar to run the AI-assisted workflow and keep usage tied to your account.")
    if st.button("Run supervised agent workflow", key="run_supervised_workflow", disabled=login_required):
        workflow_view_model = _run_supervised_workflow_with_progress(workflow_view_model)

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
