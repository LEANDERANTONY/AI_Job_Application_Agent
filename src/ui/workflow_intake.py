from src.config import DEMO_JOB_DESCRIPTION_DIR, DEMO_RESUME_DIR
from src.parsers.jd import parse_jd_text
from src.parsers.resume import parse_resume_document
from src.schemas import CandidateProfile, EducationEntry, WorkExperience
from src.services.profile_service import build_candidate_profile_from_resume
from src.ui.state import (
    CANDIDATE_PROFILE_RESUME,
    JOB_DESCRIPTION_RAW,
    JOB_DESCRIPTION_SOURCE,
    RESUME_DOCUMENT,
    get_state,
    set_active_candidate_profile,
    store_resume_intake,
)


def _load_sample_resume(filename):
    with (DEMO_RESUME_DIR / filename).open("rb") as file_handle:
        return parse_resume_document(file_handle, source=f"sample:{filename}")


def _load_sample_jd(filename):
    with (DEMO_JOB_DESCRIPTION_DIR / filename).open("rb") as file_handle:
        return parse_jd_text(file_handle)


def get_resume_page_state():
    return get_state(RESUME_DOCUMENT), _coerce_candidate_profile(get_state(CANDIDATE_PROFILE_RESUME))


def _coerce_candidate_profile(candidate_profile):
    if candidate_profile is None or isinstance(candidate_profile, CandidateProfile):
        return candidate_profile
    if not isinstance(candidate_profile, dict):
        return None
    return CandidateProfile(
        full_name=str(candidate_profile.get("full_name", "") or ""),
        location=str(candidate_profile.get("location", "") or ""),
        source=str(candidate_profile.get("source", "") or ""),
        resume_text=str(candidate_profile.get("resume_text", "") or ""),
        skills=[str(item) for item in candidate_profile.get("skills", []) or []],
        experience=[
            WorkExperience(
                title=str(item.get("title", "") or ""),
                organization=str(item.get("organization", "") or ""),
                location=str(item.get("location", "") or ""),
                description=str(item.get("description", "") or ""),
                start=item.get("start"),
                end=item.get("end"),
            )
            for item in candidate_profile.get("experience", []) or []
            if isinstance(item, dict)
        ],
        education=[
            EducationEntry(
                institution=str(item.get("institution", "") or ""),
                degree=str(item.get("degree", "") or ""),
                field_of_study=str(item.get("field_of_study", "") or ""),
                start=str(item.get("start", "") or ""),
                end=str(item.get("end", "") or ""),
            )
            for item in candidate_profile.get("education", []) or []
            if isinstance(item, dict)
        ],
        certifications=[str(item) for item in candidate_profile.get("certifications", []) or []],
        source_signals=[str(item) for item in candidate_profile.get("source_signals", []) or []],
    )


def use_sample_resume(filename, openai_service=None):
    resume_document = _load_sample_resume(filename)
    candidate_profile_resume = build_candidate_profile_from_resume(
        resume_document,
        openai_service=openai_service,
    )
    store_resume_intake(resume_document, candidate_profile_resume)
    return resume_document, candidate_profile_resume


def use_uploaded_resume(uploaded_file, openai_service=None):
    resume_document = parse_resume_document(uploaded_file)
    candidate_profile_resume = build_candidate_profile_from_resume(
        resume_document,
        openai_service=openai_service,
    )
    store_resume_intake(resume_document, candidate_profile_resume)
    return resume_document, candidate_profile_resume


def get_active_candidate_profile():
    candidate_profile = _coerce_candidate_profile(get_state(CANDIDATE_PROFILE_RESUME))
    if candidate_profile:
        set_active_candidate_profile(candidate_profile)
    return candidate_profile


def resolve_job_description_input(uploaded_jd=None, selected_sample="None", pasted_text=""):
    jd_text = get_state(JOB_DESCRIPTION_RAW, "")
    jd_source = get_state(JOB_DESCRIPTION_SOURCE, "Session cache")

    if uploaded_jd is not None:
        jd_text = parse_jd_text(uploaded_jd)
        jd_source = "Uploaded file"
    elif selected_sample != "None":
        jd_text = _load_sample_jd(selected_sample)
        jd_source = f"Sample file: {selected_sample}"

    if pasted_text.strip():
        jd_text = pasted_text
        jd_source = "Pasted text"

    return jd_text, jd_source