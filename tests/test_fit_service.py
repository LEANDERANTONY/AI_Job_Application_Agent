import pytest

from src.schemas import CandidateProfile, JobDescription, JobRequirements, ResumeDocument, WorkExperience
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume


def test_build_fit_analysis_scores_grounded_match():
    candidate_profile = build_candidate_profile_from_resume(
        ResumeDocument(
            text=(
                "Leander Antony\n"
                "Chennai, India\n"
                "Python SQL Docker communication\n"
                "3 years of machine learning experience.\n"
                "Built machine learning pipelines and production apps.\n"
                "ML Engineer at Example Labs\n"
                "Led communication across teams while shipping ML services."
            ),
            filetype="TXT",
            source="uploaded",
        )
    )
    job_description = build_job_description_from_text(
        "Machine Learning Engineer\n"
        "Location: Chennai, India\n"
        "Need 3+ years of experience with Python, SQL, Docker, AWS, and communication.\n"
    )

    fit_analysis = build_fit_analysis(candidate_profile, job_description)

    assert fit_analysis.target_role == "Machine Learning Engineer"
    assert fit_analysis.readiness_label == "Strong match"
    assert fit_analysis.overall_score >= 80
    assert fit_analysis.matched_hard_skills == ["Python", "SQL", "Docker"]
    assert fit_analysis.missing_hard_skills == ["AWS"]
    assert fit_analysis.matched_soft_skills == ["communication"]
    assert "Approx. 3.0 years of experience" in fit_analysis.experience_signal


def test_build_fit_analysis_returns_weak_signal_when_jd_has_no_explicit_requirements():
    candidate_profile = build_candidate_profile_from_resume(
        ResumeDocument(
            text="Leander Antony\nChennai, India\nBuilt analytics dashboards and internal tooling.",
            filetype="TXT",
            source="uploaded",
        )
    )
    job_description = build_job_description_from_text("Generalist role focused on helping the team succeed.")

    fit_analysis = build_fit_analysis(candidate_profile, job_description)

    assert fit_analysis.overall_score == 40
    assert fit_analysis.readiness_label == "Stretch match"
    assert any("weak signal" in gap.lower() for gap in fit_analysis.gaps)


def test_build_fit_analysis_marks_low_match_when_required_skills_and_experience_are_missing():
    candidate_profile = build_candidate_profile_from_resume(
        ResumeDocument(
            text="Pat Candidate\nChennai, India\nCustomer support and scheduling background.",
            filetype="TXT",
            source="uploaded",
        )
    )
    job_description = build_job_description_from_text(
        "Machine Learning Engineer\nRequired: Python, SQL, Docker, AWS, communication.\nNeed 5+ years of experience."
    )

    fit_analysis = build_fit_analysis(candidate_profile, job_description)

    assert fit_analysis.overall_score < 40
    assert fit_analysis.readiness_label == "Low match"
    assert fit_analysis.missing_hard_skills == ["Python", "SQL", "Docker", "AWS"]
    assert "could not be inferred" in fit_analysis.experience_signal


def test_build_fit_analysis_caps_experience_score_at_full_credit():
    candidate_profile = build_candidate_profile_from_resume(
        ResumeDocument(
            text="Leander Antony\nChennai, India\nPython SQL Docker\n10 years of engineering experience.",
            filetype="TXT",
            source="uploaded",
        )
    )
    job_description = build_job_description_from_text(
        "Platform Engineer\nRequired: Python and SQL.\nNeed 3+ years of experience."
    )

    fit_analysis = build_fit_analysis(candidate_profile, job_description)

    assert fit_analysis.overall_score == 100
    assert fit_analysis.readiness_label == "Strong match"
    assert "10.0 years of experience" in fit_analysis.experience_signal


def test_build_fit_analysis_uses_minimum_half_year_for_same_year_experience():
    candidate_profile = CandidateProfile(
        full_name="Leander Antony",
        location="Chennai, India",
        resume_text="Python API delivery",
        skills=["Python"],
        experience=[
            WorkExperience(
                title="Engineer",
                organization="Example Labs",
                description="Built Python services.",
                start={"year": 2024},
                end={"year": 2024},
            )
        ],
    )
    job_description = JobDescription(
        title="Backend Engineer",
        raw_text="raw",
        cleaned_text="cleaned",
        requirements=JobRequirements(
            hard_skills=["Python"],
            experience_requirement="1+ years",
        ),
    )

    fit_analysis = build_fit_analysis(candidate_profile, job_description)

    assert "0.5 years of experience" in fit_analysis.experience_signal
    assert fit_analysis.matched_hard_skills == ["Python"]
    assert fit_analysis.overall_score == 91


def test_build_fit_analysis_requires_typed_inputs():
    with pytest.raises(TypeError, match="candidate_profile"):
        build_fit_analysis(object(), JobDescription(title="Role", raw_text="raw", cleaned_text="clean"))

    with pytest.raises(TypeError, match="job_description"):
        build_fit_analysis(CandidateProfile(full_name="Leander Antony"), object())
