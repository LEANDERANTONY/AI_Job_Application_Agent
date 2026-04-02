from html import escape
import hashlib
import re

import streamlit as st

from src.config import (
    assisted_workflow_requires_login,
)
from src.errors import BackendIntegrationError, InputValidationError
from src.job_backend_client import resolve_job_url as resolve_job_url_via_backend
from src.job_backend_client import search_jobs as search_jobs_via_backend
from src.schemas import AgentWorkflowResult, CandidateProfile, FitAnalysis, TailoredResumeDraft
from src.ui.components import render_metric_card, render_page_divider, render_section_head
from src.ui.page_artifacts import (
    render_cover_letter_artifact as _render_cover_letter_artifact,
    render_report_package as _render_report_package,
    render_tailored_resume_artifact as _render_tailored_resume_artifact,
)
from src.ui.state import (
    get_imported_job_posting,
    get_imported_job_summary_signature,
    get_imported_job_summary_view,
    get_job_search_import_notice,
    get_job_search_results,
    is_authenticated,
    request_menu_navigation,
    set_imported_job_posting,
    set_imported_job_summary_signature,
    set_imported_job_summary_view,
    set_job_search_import_notice,
    set_job_search_results,
    set_openai_session_usage,
)
from src.ui.workflow import (
    build_ai_session_view_model,
    build_application_report_view_model,
    build_cover_letter_artifact_view_model,
    build_job_workflow_view_model,
    build_tailored_resume_artifact_view_model,
    get_resume_page_state,
    job_search_backend_enabled,
    refresh_daily_quota_status,
    resolve_job_description_input,
    run_supervised_workflow,
    store_job_description_inputs,
    use_uploaded_resume,
)
from src.services.jd_summary_service import generate_job_summary_view
from src.services.job_service import build_job_description_from_text, extract_job_summary_sections


def _go_to(menu_name):
    request_menu_navigation(menu_name)
    st.rerun()


def _load_job_posting_into_jd_flow(job_posting):
    job_text = str(job_posting.get("description_text", "") or "").strip()
    if not job_text:
        raise BackendIntegrationError("Resolved job posting did not include usable description text.")
    job_description = build_job_description_from_text(job_text)
    source_label = "Imported from {source}".format(
        source=str(job_posting.get("source", "backend")).title()
    )
    store_job_description_inputs(job_text, source_label, job_description)
    set_imported_job_posting(job_posting)
    set_imported_job_summary_signature(None)
    set_imported_job_summary_view(None)
    set_job_search_import_notice(
        {
            "level": "success",
            "message": "Imported {title} and loaded it into Manual JD Input.".format(
                title=job_posting.get("title", "job posting")
            ),
        }
    )
    _go_to("Manual JD Input")


def _render_list(title, items, empty_state):
    st.markdown(f"**{title}**")
    if items:
        for item in items:
            st.markdown(f"- {item}")
    else:
        st.caption(empty_state)


def _extract_compensation_text(text):
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return ""

    range_match = re.search(
        r"([A-Z][A-Za-z ]*Pay Range\s*)?([$€£]\s?\d[\d,]*(?:\.\d+)?\s*(?:-|–|—|to)\s*[$€£]?\s?\d[\d,]*(?:\.\d+)?\s*(?:USD|CAD|EUR|GBP|AUD|INR)?)",
        normalized,
        re.IGNORECASE,
    )
    if range_match:
        prefix = (range_match.group(1) or "").strip()
        amount = (range_match.group(2) or "").strip()
        return f"{prefix} {amount}".strip()

    comp_match = re.search(
        r"((?:salary|compensation|pay range)[^.:]{0,30}[:\-]?\s*[$€£]?\s?\d[\d,]*(?:\.\d+)?(?:\s*(?:-|–|—|to)\s*[$€£]?\s?\d[\d,]*(?:\.\d+)?)?(?:\s*(?:USD|CAD|EUR|GBP|AUD|INR|per year|annually))?)",
        normalized,
        re.IGNORECASE,
    )
    if comp_match:
        return comp_match.group(1).strip()

    return ""


def _format_short_posted_label(posted_at):
    normalized = str(posted_at or "").strip()
    if not normalized:
        return ""
    return normalized[:10]


def _build_job_search_badges(job_posting):
    metadata = job_posting.get("metadata") or {}
    badges = []

    location = str(job_posting.get("location", "") or "").strip()
    employment_type = str(job_posting.get("employment_type", "") or "").strip()
    posted_label = _format_short_posted_label(job_posting.get("posted_at"))
    compensation = _extract_compensation_text(job_posting.get("description_text", "") or "")

    if employment_type:
        badges.append(employment_type)
    if location:
        badges.append(location)
    if posted_label:
        badges.append(f"Posted {posted_label}")
    if compensation:
        badges.append(compensation)

    departments = [str(item).strip() for item in metadata.get("departments", []) if str(item).strip()]
    if departments:
        badges.append(departments[0])

    unique_badges = []
    seen = set()
    for badge in badges:
        lowered = badge.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique_badges.append(badge)
    return unique_badges[:5]


def _render_badge_row(badges):
    if not badges:
        return
    badge_markup = "".join(
        """
        <span style="
            display:inline-block;
            background:rgba(96, 165, 250, 0.12);
            color:#dbeafe;
            border:1px solid rgba(96, 165, 250, 0.22);
            border-radius:999px;
            padding:0.18rem 0.55rem;
            margin:0 0.38rem 0.38rem 0;
            font-size:0.74rem;
            font-weight:700;
            line-height:1.3;
        ">{badge}</span>
        """.format(badge=escape(str(badge)))
        for badge in badges
    )
    st.markdown(badge_markup, unsafe_allow_html=True)


def _render_job_search_source_status(search_results_payload):
    source_status = dict((search_results_payload or {}).get("source_status") or {})
    if not source_status:
        return

    board_statuses = {
        key: value
        for key, value in source_status.items()
        if key not in {"backend", "greenhouse", "lever"}
    }
    if not board_statuses:
        return

    matched_count = sum(1 for value in board_statuses.values() if value == "matched")
    no_match_count = sum(1 for value in board_statuses.values() if value == "no_match")
    empty_count = sum(1 for value in board_statuses.values() if value == "empty")
    error_count = sum(1 for value in board_statuses.values() if value == "error")
    searched_count = len(board_statuses)

    st.markdown("### Search Coverage")
    coverage_cols = st.columns(4)
    coverage_cards = [
        ("Boards Searched", str(searched_count), "Configured boards checked for this search."),
        ("Matched Boards", str(matched_count), "Boards that returned at least one matching role."),
        ("No Match", str(no_match_count + empty_count), "Boards checked but without current matching roles."),
        ("Unavailable", str(error_count), "Boards that failed to respond right now."),
    ]
    for col, (label, value, note) in zip(coverage_cols, coverage_cards):
        with col:
            render_metric_card(label, value, note, dense=True, slim=True)

    if error_count:
        failed_boards = sorted(key for key, value in board_statuses.items() if value == "error")
        st.caption("Unavailable right now: {boards}".format(boards=", ".join(failed_boards)))


def _render_job_search_context_panel(backend_enabled):
    render_metric_card(
        "Search Layer",
        "Backend-Ready" if backend_enabled else "Disabled",
        "Search and URL import both use the FastAPI job backend when enabled.",
    )
    render_metric_card(
        "Active Sources",
        "Greenhouse + Lever",
        "Current search runs across the configured Greenhouse boards and Lever sites for technical roles.",
        dense=True,
        slim=True,
    )
    render_metric_card(
        "Default Ordering",
        "Most Recent First",
        "Matching jobs are shown in descending posted order so fresh roles surface first.",
        dense=True,
        slim=True,
    )
    with st.expander("Search Tips", expanded=True):
        st.markdown("- Use broad searches like `software engineer`, `backend engineer`, or `data scientist`.")
        st.markdown("- Add a location only when you want to narrow results; leaving it blank keeps the search broad.")
        st.markdown("- Paste a direct Greenhouse or Lever job URL when you already know the exact role to analyze.")


def _render_job_search_results_header(search_results_payload):
    query_payload = dict((search_results_payload or {}).get("query") or {})
    results = list((search_results_payload or {}).get("results") or [])
    query_label = str(query_payload.get("query", "") or "").strip()
    location_label = str(query_payload.get("location", "") or "").strip()
    posted_within_days = query_payload.get("posted_within_days")
    remote_only = bool(query_payload.get("remote_only"))

    summary_bits = []
    if query_label:
        summary_bits.append("Query: {query}".format(query=query_label))
    if location_label:
        summary_bits.append("Location: {location}".format(location=location_label))
    if remote_only:
        summary_bits.append("Remote only")
    if posted_within_days:
        summary_bits.append("Last {days} days".format(days=posted_within_days))

    render_section_head(
        "Matching Jobs",
        " | ".join(summary_bits) if summary_bits else "Current search results from the active backend query.",
    )
    result_cols = st.columns(2)
    with result_cols[0]:
        render_metric_card(
            "Jobs Found",
            str(len(results)),
            "Current result count returned by the backend search.",
            dense=True,
            slim=True,
        )
    with result_cols[1]:
        render_metric_card(
            "Sort Order",
            "Newest First",
            "Search results are currently sorted by the freshest matching postings.",
            dense=True,
            slim=True,
        )


def _render_summary_cards(cards, columns_per_row=3):
    visible_cards = [
        (label, value, note)
        for label, value, note in cards
        if str(value or "").strip()
    ]
    if not visible_cards:
        return

    for index in range(0, len(visible_cards), columns_per_row):
        row = visible_cards[index:index + columns_per_row]
        cols = st.columns(len(row))
        for col, (label, value, note) in zip(cols, row):
            with col:
                render_metric_card(label, value, note, dense=True, slim=True)


def _job_summary_signature(job_description, imported_job_posting):
    source_job_id = ""
    if imported_job_posting:
        source_job_id = str(imported_job_posting.get("id", "") or "").strip()
    payload = "||".join(
        [
            source_job_id,
            str(job_description.title or ""),
            str(job_description.location or ""),
            str(job_description.cleaned_text or ""),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolve_job_summary_view(job_description, imported_job_posting=None):
    deterministic_sections = extract_job_summary_sections(
        job_description.cleaned_text,
        title=job_description.title,
    )
    deterministic_view = {"mode": "deterministic", "sections": deterministic_sections}

    signature = _job_summary_signature(job_description, imported_job_posting)
    cached_signature = get_imported_job_summary_signature()
    cached_view = get_imported_job_summary_view()
    if cached_signature == signature and cached_view:
        return cached_view

    if not is_authenticated():
        set_imported_job_summary_signature(signature)
        set_imported_job_summary_view(deterministic_view)
        return deterministic_view

    ai_session = build_ai_session_view_model()
    openai_service = ai_session.openai_service if ai_session else None
    if not openai_service or not openai_service.is_available():
        set_imported_job_summary_signature(signature)
        set_imported_job_summary_view(deterministic_view)
        return deterministic_view

    with st.spinner("Generating readable job summary..."):
        summary_view = generate_job_summary_view(
            openai_service=openai_service,
            job_description=job_description,
            imported_job_posting=imported_job_posting,
        )
    set_openai_session_usage(openai_service.get_usage_snapshot())
    refresh_daily_quota_status(force=True)
    set_imported_job_summary_signature(signature)
    set_imported_job_summary_view(summary_view)
    return summary_view


def _render_job_summary_sections(summary_view, empty_state):
    st.markdown("**Job Summary**")
    sections = list((summary_view or {}).get("sections") or [])
    if not sections:
        st.caption(empty_state)
        return

    mode = str((summary_view or {}).get("mode", "deterministic"))
    if mode == "ai":
        st.caption("Readable summary generated from the imported JD. Workflow analysis still uses the deterministic parsed JD.")
    else:
        st.caption("Showing the deterministic structured JD view.")

    for section in sections:
        section_title = section.get("title") or "Overview"
        items = [str(item).strip() for item in section.get("items", []) if str(item).strip()]
        if not items:
            continue
        st.markdown(f"**{section_title}**")
        body = "".join(
            """
            <div style="
                display:flex;
                align-items:flex-start;
                gap:0.55rem;
                margin:0 0 0.52rem 0;
                color:#e7eefc;
                line-height:1.7;
            ">
                <div style="
                    width:0.38rem;
                    height:0.38rem;
                    min-width:0.38rem;
                    border-radius:999px;
                    background:#60a5fa;
                    margin-top:0.56rem;
                "></div>
                <div>{text}</div>
            </div>
            """.format(text=escape(item))
            for item in items
        )
        st.markdown(
            """
            <div style="
                background:rgba(255,255,255,0.05);
                border:1px solid rgba(148, 163, 184, 0.18);
                border-radius:14px;
                padding:0.82rem 0.95rem 0.38rem;
                margin:0.15rem 0 0.7rem 0;
            ">
                {body}
            </div>
            """.format(body=body),
            unsafe_allow_html=True,
        )


def _render_job_review_panel(job_description, *, imported_job_posting=None, expander_title="Review Job Details"):
    requirements = job_description.requirements

    with st.expander(expander_title, expanded=False):
        if imported_job_posting:
            metadata = imported_job_posting.get("metadata") or {}
            departments = [str(item) for item in metadata.get("departments", []) if str(item).strip()]
            offices = [str(item) for item in metadata.get("offices", []) if str(item).strip()]
            url = imported_job_posting.get("url") or ""
            if url:
                st.markdown(f"**Job URL:** {url}")
            if departments:
                st.markdown(f"**Departments:** {', '.join(departments)}")
            if offices:
                st.markdown(f"**Offices:** {', '.join(offices)}")

        skill_cols = st.columns(2)
        with skill_cols[0]:
            _render_list("Hard Skills Required", requirements.hard_skills, "No hard skills extracted yet.")
        with skill_cols[1]:
            _render_list("Soft Skills Required", requirements.soft_skills, "No soft skills extracted yet.")

        summary_view = _resolve_job_summary_view(job_description, imported_job_posting)
        _render_job_summary_sections(
            summary_view,
            empty_state="No job summary available.",
        )


def _render_imported_job_summary(imported_job_posting, job_description):
    if not imported_job_posting:
        return

    requirements = job_description.requirements
    company = imported_job_posting.get("company") or "Unknown"
    location = imported_job_posting.get("location") or job_description.location or "Unknown"
    employment_type = imported_job_posting.get("employment_type") or "Not specified"
    posted_at = imported_job_posting.get("posted_at") or "Unknown"
    compensation = _extract_compensation_text(job_description.cleaned_text) or "Not listed"
    role_with_company = job_description.title or "Unknown"
    if company and company != "Unknown":
        role_with_company = f"{role_with_company} at {company}"
    imported_cards = [
        ("Target Role", role_with_company if role_with_company != "Unknown" else "", "Primary role for this JD."),
        ("Compensation", "" if compensation == "Not listed" else compensation, "Compensation details from the JD."),
        ("Location", "" if location == "Unknown" else location, "Imported job location."),
        ("Employment", "" if employment_type == "Not specified" else employment_type, "Employment type if available."),
        (
            "Posted",
            posted_at[:10] if posted_at and posted_at != "Unknown" else "",
            "Posting date from provider.",
        ),
        (
            "Experience",
            requirements.experience_requirement or "",
            "Experience signal from the JD.",
        ),
    ]
    _render_summary_cards(imported_cards)

    _render_job_review_panel(
        job_description,
        imported_job_posting=imported_job_posting,
        expander_title="Review Imported Job Details",
    )


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


def _render_job_search_result_card(job_posting, index):
    company = str(job_posting.get("company", "") or "Unknown")
    title = str(job_posting.get("title", "") or "Unknown role")
    source = str(job_posting.get("source", "") or "backend").title()
    summary = str(job_posting.get("summary", "") or "").strip()
    if len(summary) > 220:
        summary = summary[:220].rsplit(" ", 1)[0].strip() + "..."
    badges = _build_job_search_badges(job_posting)

    st.markdown(
        """
        <div style="
            background:rgba(255,255,255,0.05);
            border:1px solid rgba(148, 163, 184, 0.18);
            border-radius:16px;
            padding:0.9rem 0.95rem 0.82rem;
            margin:0 0 0.8rem 0;
        ">
            <div style="font-size:1rem; font-weight:800; color:#e7eefc; margin-bottom:0.2rem;">{title}</div>
            <div style="font-size:0.92rem; color:#93c5fd; font-weight:700; margin-bottom:0.35rem;">{company}</div>
            <div style="font-size:0.78rem; color:#94a3b8; margin-bottom:0.55rem;">Source: {source}</div>
            <div style="font-size:0.85rem; color:#e2e8f0; line-height:1.55;">{summary}</div>
        </div>
        """.format(
            title=escape(title),
            company=escape(company),
            source=escape(source),
            summary=escape(summary or "No summary available."),
        ),
        unsafe_allow_html=True,
    )
    _render_badge_row(badges)
    actions = st.columns([1.0, 1.0])
    with actions[0]:
        if st.button("Use This Job", key=f"job_search_load_{index}"):
            _load_job_posting_into_jd_flow(job_posting)
    with actions[1]:
        job_url = str(job_posting.get("url", "") or "").strip()
        if job_url:
            st.link_button("Open Posting", job_url, use_container_width=True)


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
        "Search broad technical roles across configured boards, or paste a supported job URL to load it directly.",
    )
    left_col, right_col = st.columns([1.2, 1.0])
    with left_col:
        backend_enabled = job_search_backend_enabled()
        render_section_head(
            "Search Boards",
            "Find recent engineering roles across the configured backend-connected boards.",
        )
        search_query = st.text_input(
            "Search Query",
            placeholder="Software engineer, backend engineer, data scientist, machine learning engineer...",
            disabled=not backend_enabled,
            key="job_search_query",
        )
        search_location = st.text_input(
            "Preferred Location",
            placeholder="Bengaluru, Chennai, Remote, Toronto...",
            disabled=not backend_enabled,
            key="job_search_location",
        )
        search_filters = st.columns(2)
        with search_filters[0]:
            remote_only = st.checkbox(
                "Remote only",
                value=False,
                disabled=not backend_enabled,
                key="job_search_remote_only",
            )
        with search_filters[1]:
            posted_within_days = st.selectbox(
                "Posted Within",
                options=[None, 3, 7, 14, 30],
                format_func=lambda value: "Any time" if value is None else f"Last {value} days",
                disabled=not backend_enabled,
                key="job_search_posted_within_days",
            )
        search_clicked = st.button(
            "Search Jobs",
            disabled=not backend_enabled,
            key="job_search_submit",
        )
        st.markdown("---")
        render_section_head(
            "Direct Import",
            "Already have a supported job link? Load it straight into the JD workflow.",
        )
        job_url = st.text_input(
            "Paste Job URL",
            placeholder="Paste a supported job URL, for example a Greenhouse posting.",
            disabled=not backend_enabled,
        )
        import_clicked = st.button(
            "Load Job Into JD Flow",
            disabled=not backend_enabled,
        )
        notice = get_job_search_import_notice()
        if notice:
            level = notice.get("level", "info")
            message = notice.get("message", "")
            if message:
                if level == "success":
                    st.success(message)
                elif level == "warning":
                    st.warning(message)
                else:
                    st.info(message)
        if not backend_enabled:
            st.info("Job backend integration is disabled in the current environment.")
        else:
            if search_clicked:
                try:
                    response_payload = search_jobs_via_backend(
                        query=search_query,
                        location=search_location,
                        remote_only=remote_only,
                        posted_within_days=posted_within_days,
                        page_size=12,
                        source_filters=["greenhouse", "lever"],
                    )
                    set_job_search_results(response_payload)
                    set_job_search_import_notice(
                        {
                            "level": "info",
                            "message": "Found {count} jobs for your current search.".format(
                                count=len(response_payload.get("results", []) or [])
                            ),
                        }
                    )
                    st.rerun()
                except BackendIntegrationError as error:
                    set_job_search_import_notice(
                        {
                            "level": "warning",
                            "message": error.user_message,
                        }
                    )
                    st.rerun()
            if import_clicked:
                try:
                    response_payload = resolve_job_url_via_backend(job_url)
                    if response_payload.get("status") != "ok" or not response_payload.get("job_posting"):
                        raise BackendIntegrationError(
                            response_payload.get("error_message")
                            or "That job URL could not be resolved into a supported posting."
                        )
                    _load_job_posting_into_jd_flow(response_payload["job_posting"])
                except BackendIntegrationError as error:
                    set_job_search_import_notice(
                        {
                            "level": "warning",
                            "message": error.user_message,
                        }
                    )
                    st.rerun()

        search_results_payload = get_job_search_results() or {}
        search_results = list(search_results_payload.get("results", []) or [])
        if search_results:
            result_actions = st.columns([1.0, 1.0, 3.0])
            with result_actions[0]:
                clear_results_clicked = st.button("Clear Results", key="job_search_clear_results")
            if clear_results_clicked:
                set_job_search_results(None)
                set_job_search_import_notice(None)
                st.rerun()
            _render_job_search_source_status(search_results_payload)
            _render_job_search_results_header(search_results_payload)
            for index, job_posting in enumerate(search_results):
                _render_job_search_result_card(job_posting, index)
        elif search_results_payload:
            clear_results_clicked = st.button("Clear Results", key="job_search_clear_results_empty")
            if clear_results_clicked:
                set_job_search_results(None)
                set_job_search_import_notice(None)
                st.rerun()
            _render_job_search_source_status(search_results_payload)
            st.info("No current jobs matched this search. Try a broader query or location.")
    with right_col:
        _render_job_search_context_panel(job_search_backend_enabled())
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

    imported_job_posting = get_imported_job_posting()
    if imported_job_posting and not (jd_source and str(jd_source).startswith("Imported from ")):
        set_imported_job_posting(None)
        imported_job_posting = None

    st.caption(f"JD Source: {jd_source if jd_text else 'None'}")
    st.markdown("---")
    workflow_view_model = build_job_workflow_view_model(jd_text, jd_source)
    if not workflow_view_model.job_description:
        return

    job_description = workflow_view_model.job_description

    display_title = job_description.title or "Unknown"
    if (not job_description.title or job_description.title.lower() == "unknown role") and imported_job_posting:
        display_title = imported_job_posting.get("title") or display_title
    job_description.title = display_title

    if imported_job_posting:
        _render_imported_job_summary(imported_job_posting, job_description)
    else:
        manual_cards = [
            ("Target Role", "" if display_title == "Unknown" else display_title, "Structured title extracted from the JD."),
            ("Compensation", _extract_compensation_text(job_description.cleaned_text), "Compensation details detected in the JD."),
            ("Location", job_description.location or "", "Location detected in the JD."),
            ("Experience", job_description.requirements.experience_requirement or "", "Experience signal extracted from the JD."),
            (
                "Hard Skills",
                str(len(job_description.requirements.hard_skills)) if job_description.requirements.hard_skills else "",
                "Matched hard-skill keywords.",
            ),
            (
                "Soft Skills",
                str(len(job_description.requirements.soft_skills)) if job_description.requirements.soft_skills else "",
                "Matched soft-skill keywords.",
            ),
        ]
        _render_summary_cards(manual_cards)
        _render_job_review_panel(job_description, expander_title="Review Job Details")

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
