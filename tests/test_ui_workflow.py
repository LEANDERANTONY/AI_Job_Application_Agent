from src.schemas import CandidateProfile, JobDescription, JobRequirements, ResumeDocument
from src.ui import workflow


def test_resolve_job_description_input_prefers_pasted_text(monkeypatch):
    monkeypatch.setattr(workflow, "get_state", lambda key, default=None: default)
    monkeypatch.setattr(workflow, "parse_jd_text", lambda uploaded_jd: "uploaded text")
    monkeypatch.setattr(workflow, "_load_sample_jd", lambda filename: "sample text")

    jd_text, jd_source = workflow.resolve_job_description_input(
        uploaded_jd=object(),
        selected_sample="sample.txt",
        pasted_text="pasted text",
    )

    assert jd_text == "pasted text"
    assert jd_source == "Pasted text"


def test_use_sample_resume_stores_resume_and_profile(monkeypatch):
    resume_document = ResumeDocument(text="resume text", filetype="TXT", source="sample:test")
    candidate_profile = CandidateProfile(full_name="Leander Antony")
    stored = {}

    monkeypatch.setattr(workflow, "_load_sample_resume", lambda filename: resume_document)
    monkeypatch.setattr(
        workflow,
        "build_candidate_profile_from_resume",
        lambda document: candidate_profile,
    )
    monkeypatch.setattr(
        workflow,
        "store_resume_intake",
        lambda document, profile: stored.update({"document": document, "profile": profile}),
    )

    result_document, result_profile = workflow.use_sample_resume("sample.txt")

    assert result_document is resume_document
    assert result_profile is candidate_profile
    assert stored["document"] is resume_document
    assert stored["profile"] is candidate_profile


def test_build_job_workflow_view_model_returns_job_only_without_candidate_profile(monkeypatch):
    job_description = JobDescription(
        title="Machine Learning Engineer",
        raw_text="raw",
        cleaned_text="cleaned",
        requirements=JobRequirements(hard_skills=["Python"]),
    )

    monkeypatch.setattr(workflow, "build_job_description_from_text", lambda text: job_description)
    monkeypatch.setattr(workflow, "store_job_description_inputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(workflow, "get_active_candidate_profile", lambda: None)

    view_model = workflow.build_job_workflow_view_model("jd text", "Pasted text")

    assert view_model.job_description is job_description
    assert view_model.candidate_profile is None
    assert view_model.fit_analysis is None
    assert view_model.ai_session is None