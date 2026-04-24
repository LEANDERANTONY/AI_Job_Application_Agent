import base64

from fastapi.testclient import TestClient

from backend.app import app


client = TestClient(app)


def _encode_text_file_payload(filename: str, text: str):
    return {
        "filename": filename,
        "mime_type": "text/plain",
        "content_base64": base64.b64encode(text.encode("utf-8")).decode("utf-8"),
    }


def test_workspace_resume_upload_parses_candidate_profile():
    response = client.post(
        "/api/workspace/resume/upload",
        json=_encode_text_file_payload(
            "resume.txt",
            (
                "Leander Antony\n"
                "Chennai, India\n"
                "leander@example.com\n"
                "Python SQL Docker Communication\n"
                "Experience\n"
                "AI Engineer, Example Labs\n"
                "Jan 2023 - Jan 2025\n"
                "Built production ML APIs and evaluation workflows.\n"
            ),
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["resume_document"]["filetype"] == "TXT"
    assert payload["candidate_profile"]["full_name"] == "Leander Antony"
    assert "Python" in payload["candidate_profile"]["skills"]


def test_workspace_job_description_upload_parses_role_and_summary():
    response = client.post(
        "/api/workspace/job-description/upload",
        json=_encode_text_file_payload(
            "job.txt",
            (
                "Machine Learning Engineer\n"
                "Location: Bengaluru, India\n"
                "Required: Python, SQL, Docker, communication.\n"
                "Need 3+ years of experience.\n"
                "Preferred: AWS and production LLM systems.\n"
            ),
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_description"]["title"] == "Machine Learning Engineer"
    assert payload["job_description"]["requirements"]["hard_skills"]
    assert payload["jd_summary_view"]["sections"]


def test_resume_builder_session_can_progress_to_review():
    start_response = client.post("/api/workspace/resume-builder/start")

    assert start_response.status_code == 200
    session_id = start_response.json()["session_id"]

    message_payloads = [
        "Leander Antony\nChennai, India\nleander@example.com\n+91 9999999999\nlinkedin.com/in/leander",
        "Machine Learning Engineer\nAI engineer with product-focused ML experience across APIs, evaluation, and developer tooling.",
        "AI Engineer at Example Labs\nJan 2023 - Present\nBuilt ML APIs used by production teams.\nImproved evaluation workflows for model quality.",
        "Anna University | B.E. Computer Science\nAWS Certified Machine Learning Specialty",
        "Python, FastAPI, Docker, LLMs, SQL",
    ]

    latest_payload = None
    for message in message_payloads:
        response = client.post(
            "/api/workspace/resume-builder/message",
            json={
                "session_id": session_id,
                "message": message,
                "input_mode": "text",
            },
        )
        assert response.status_code == 200
        latest_payload = response.json()

    assert latest_payload is not None
    assert latest_payload["status"] == "reviewing"
    assert latest_payload["current_step"] == "review"
    assert latest_payload["ready_to_generate"] is True
    assert latest_payload["draft_profile"]["target_role"] == "Machine Learning Engineer"
    assert "Python" in latest_payload["draft_profile"]["skills"]


def test_resume_builder_generate_and_commit_returns_workspace_profile():
    start_response = client.post("/api/workspace/resume-builder/start")

    assert start_response.status_code == 200
    session_id = start_response.json()["session_id"]

    for message in [
        "Leander Antony\nChennai, India\nleander@example.com\n+91 9999999999",
        "Machine Learning Engineer\nAI engineer with ML platform and applied AI experience.",
        "AI Engineer at Example Labs\nJan 2023 - Present\nBuilt ML APIs and developer workflows.",
        "Anna University | B.E. Computer Science",
        "Python, FastAPI, Docker, SQL",
    ]:
        response = client.post(
            "/api/workspace/resume-builder/message",
            json={
                "session_id": session_id,
                "message": message,
                "input_mode": "text",
            },
        )
        assert response.status_code == 200

    generate_response = client.post(
        "/api/workspace/resume-builder/generate",
        json={"session_id": session_id},
    )

    assert generate_response.status_code == 200
    generated_payload = generate_response.json()
    assert generated_payload["status"] == "ready"
    assert generated_payload["generated_resume_markdown"]
    assert generated_payload["candidate_profile"]["full_name"] == "Leander Antony"

    commit_response = client.post(
        "/api/workspace/resume-builder/commit",
        json={"session_id": session_id},
    )

    assert commit_response.status_code == 200
    commit_payload = commit_response.json()
    assert commit_payload["resume_document"]["source"] == "assistant_builder"
    assert commit_payload["candidate_profile"]["source"] == "assistant_builder"
    assert commit_payload["generated_resume_markdown"]


def test_resume_builder_update_route_applies_draft_changes():
    start_response = client.post("/api/workspace/resume-builder/start")

    assert start_response.status_code == 200
    session_id = start_response.json()["session_id"]

    update_response = client.post(
        "/api/workspace/resume-builder/update",
        json={
            "session_id": session_id,
            "draft_profile": {
                "full_name": "Leander Antony",
                "location": "Chennai, India",
                "target_role": "Machine Learning Engineer",
                "professional_summary": "AI engineer with product and platform experience.",
                "skills": ["Python", "FastAPI", "Docker"],
                "contact_lines": ["leander@example.com", "+91 9999999999"],
            },
        },
    )

    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["draft_profile"]["full_name"] == "Leander Antony"
    assert payload["draft_profile"]["target_role"] == "Machine Learning Engineer"
    assert "Docker" in payload["draft_profile"]["skills"]


def test_resume_builder_latest_endpoint_returns_saved_session(monkeypatch):
    monkeypatch.setattr(
        "backend.routers.workspace.load_latest_resume_builder_session",
        lambda access_token, refresh_token: {
            "status": "available",
            "session": {
                "session_id": "builder-123",
                "status": "collecting",
                "current_step": "experience",
                "completed_steps": 2,
                "total_steps": 5,
                "progress_percent": 40,
                "assistant_message": "Tell me about your most relevant experience.",
                "draft_profile": {
                    "full_name": "Leander Antony",
                    "location": "Chennai, India",
                    "contact_lines": ["leander@example.com"],
                    "target_role": "Machine Learning Engineer",
                    "professional_summary": "AI engineer with ML platform experience.",
                    "experience_notes": "",
                    "education_notes": "",
                    "skills": ["Python"],
                    "certifications": [],
                },
                "generated_resume_markdown": "",
                "generated_resume_plain_text": "",
                "ready_to_generate": False,
                "ready_to_commit": False,
            },
        },
    )

    response = client.get(
        "/api/workspace/resume-builder/latest",
        headers={
            "X-Auth-Access-Token": "access-token",
            "X-Auth-Refresh-Token": "refresh-token",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "available"
    assert payload["session"]["current_step"] == "experience"
    assert payload["session"]["draft_profile"]["target_role"] == "Machine Learning Engineer"


def test_workspace_analyze_returns_fit_and_artifacts_without_assisted_run():
    response = client.post(
        "/api/workspace/analyze",
        json={
            "resume_text": (
                "Leander Antony\n"
                "Chennai, India\n"
                "Python SQL Docker Communication AWS\n"
                "Experience\n"
                "AI Engineer, Example Labs\n"
                "Jan 2023 - Jan 2025\n"
                "Built production ML APIs and evaluation workflows.\n"
            ),
            "resume_filetype": "TXT",
            "resume_source": "workspace",
            "job_description_text": (
                "Machine Learning Engineer\n"
                "Location: Chennai, India\n"
                "Required: Python, SQL, Docker, AWS, communication.\n"
                "Need 3+ years of experience.\n"
            ),
            "run_assisted": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workflow"]["mode"] == "deterministic_preview"
    assert payload["fit_analysis"]["overall_score"] >= 0
    assert payload["artifacts"]["tailored_resume"]["markdown"]
    assert payload["artifacts"]["cover_letter"]["markdown"]
    assert payload["artifacts"]["report"]["markdown"]


def test_workspace_analyze_job_start_returns_job_handle(monkeypatch):
    monkeypatch.setattr(
        "backend.routers.workspace.start_workspace_analysis_job",
        lambda **kwargs: {
            "job_id": "job-123",
            "status": "queued",
            "stage_title": "Workflow crew",
            "stage_detail": "Preparing the first agent.",
            "progress_percent": 3,
        },
    )

    response = client.post(
        "/api/workspace/analyze-jobs",
        json={
            "resume_text": "Leander Antony\nPython\nExperience\nAI Engineer",
            "resume_filetype": "TXT",
            "resume_source": "workspace",
            "job_description_text": "Machine Learning Engineer\nRequired: Python",
            "run_assisted": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == "job-123"
    assert payload["status"] == "queued"
    assert payload["stage_title"] == "Workflow crew"


def test_workspace_analyze_job_status_returns_completed_result(monkeypatch):
    monkeypatch.setattr(
        "backend.routers.workspace.get_workspace_analysis_job",
        lambda job_id: {
            "job_id": job_id,
            "status": "completed",
            "stage_title": "Workflow crew",
            "stage_detail": "All agents are done.",
            "progress_percent": 100,
            "error_message": None,
            "result": {
                "resume_document": {"text": "resume", "filetype": "TXT", "source": "workspace"},
                "candidate_profile": {
                    "full_name": "Leander Antony",
                    "location": "Chennai, India",
                    "contact_lines": [],
                    "source": "workspace",
                    "resume_text": "resume",
                    "skills": [],
                    "experience": [],
                    "education": [],
                    "certifications": [],
                    "source_signals": [],
                },
                "job_description": {
                    "title": "Machine Learning Engineer",
                    "raw_text": "jd",
                    "cleaned_text": "jd",
                    "location": None,
                    "salary": None,
                    "requirements": {
                        "hard_skills": [],
                        "soft_skills": [],
                        "experience_requirement": None,
                        "must_haves": [],
                        "nice_to_haves": [],
                    },
                },
                "jd_summary_view": {
                    "headline": "headline",
                    "summary": "summary",
                    "sections": [],
                    "fit_signals": [],
                    "interview_focus": [],
                },
                "fit_analysis": {
                    "target_role": "Machine Learning Engineer",
                    "overall_score": 50,
                    "readiness_label": "Promising",
                    "matched_hard_skills": [],
                    "missing_hard_skills": [],
                    "matched_soft_skills": [],
                    "missing_soft_skills": [],
                    "experience_signal": "",
                    "strengths": [],
                    "gaps": [],
                    "recommendations": [],
                },
                "tailored_draft": {
                    "target_role": "Machine Learning Engineer",
                    "professional_summary": "",
                    "highlighted_skills": [],
                    "priority_bullets": [],
                    "gap_mitigation_steps": [],
                },
                "agent_result": None,
                "artifacts": {
                    "tailored_resume": {
                        "title": "resume",
                        "filename_stem": "resume",
                        "summary": "",
                        "markdown": "",
                        "plain_text": "",
                        "theme": "classic_ats",
                        "header": {
                            "full_name": "Leander Antony",
                            "location": "Chennai, India",
                            "contact_lines": [],
                        },
                        "target_role": "Machine Learning Engineer",
                        "professional_summary": "",
                        "highlighted_skills": [],
                        "experience_entries": [],
                        "education_entries": [],
                        "certifications": [],
                        "change_log": [],
                        "validation_notes": [],
                    },
                    "cover_letter": {
                        "title": "cover",
                        "filename_stem": "cover",
                        "summary": "",
                        "markdown": "",
                        "plain_text": "",
                    },
                    "report": {
                        "title": "report",
                        "filename_stem": "report",
                        "summary": "",
                        "markdown": "",
                        "plain_text": "",
                    },
                },
                "workflow": {
                    "mode": "openai",
                    "assisted_requested": True,
                    "assisted_available": True,
                    "review_approved": True,
                    "fallback_reason": "",
                },
                "imported_job_posting": None,
            },
        },
    )

    response = client.get("/api/workspace/analyze-jobs/job-123")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["progress_percent"] == 100
    assert payload["result"]["job_description"]["title"] == "Machine Learning Engineer"


def test_workspace_analyze_prefers_imported_job_title_when_parser_cannot_extract_it():
    response = client.post(
        "/api/workspace/analyze",
        json={
            "resume_text": (
                "Leander Antony\n"
                "Chennai, India\n"
                "Python SQL Docker Communication AWS\n"
                "Experience\n"
                "AI Engineer, Example Labs\n"
                "Jan 2023 - Jan 2025\n"
                "Built production ML APIs and evaluation workflows.\n"
            ),
            "resume_filetype": "TXT",
            "resume_source": "workspace",
            "job_description_text": (
                "We are hiring a senior engineer to build data products and machine learning systems.\n"
                "Required: Python, SQL, Docker, AWS, communication.\n"
                "Need 5+ years of experience.\n"
            ),
            "imported_job_posting": {
                "id": "greenhouse:narvar:6930410",
                "source": "greenhouse",
                "title": "Staff Software Engineer, Machine Learning",
                "company": "Narvar",
                "location": "Bengaluru, Karnataka, India",
                "employment_type": "",
                "url": "https://job-boards.greenhouse.io/narvar/jobs/6930410",
                "summary": "Machine learning platform role.",
                "description_text": "Imported posting description",
                "posted_at": "",
                "scraped_at": "",
                "metadata": {},
            },
            "run_assisted": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_description"]["title"] == "Staff Software Engineer, Machine Learning"
    assert payload["job_description"]["location"] == "Bengaluru, Karnataka, India"
    assert "Staff Software Engineer, Machine Learning" in payload["artifacts"]["report"]["title"]
    assert "Staff Software Engineer, Machine Learning" in payload["artifacts"]["tailored_resume"]["title"]


def test_workspace_assistant_answer_uses_workspace_snapshot_context():
    analysis_response = client.post(
        "/api/workspace/analyze",
        json={
            "resume_text": (
                "Leander Antony\n"
                "Chennai, India\n"
                "Python SQL Docker Communication AWS\n"
                "Experience\n"
                "AI Engineer, Example Labs\n"
                "Jan 2023 - Jan 2025\n"
                "Built production ML APIs and evaluation workflows.\n"
            ),
            "resume_filetype": "TXT",
            "resume_source": "workspace",
            "job_description_text": (
                "Machine Learning Engineer\n"
                "Location: Chennai, India\n"
                "Required: Python, SQL, Docker, AWS, communication.\n"
                "Need 3+ years of experience.\n"
            ),
            "run_assisted": False,
        },
    )

    assert analysis_response.status_code == 200
    snapshot = analysis_response.json()

    response = client.post(
        "/api/workspace/assistant/answer",
        json={
            "question": "What are my biggest gaps for this role?",
            "current_page": "Workspace",
            "workspace_snapshot": snapshot,
            "history": [],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"]
    assert payload["sources"]


def test_workspace_save_endpoint_forwards_auth_headers(monkeypatch):
    captured = {}

    def fake_save_workspace_snapshot(*, access_token, refresh_token, workspace_snapshot):
        captured["access_token"] = access_token
        captured["refresh_token"] = refresh_token
        captured["workspace_snapshot"] = workspace_snapshot
        return {
            "status": "saved",
            "saved_workspace": {
                "job_title": "Machine Learning Engineer",
                "expires_at": "2026-04-22T00:00:00+00:00",
                "updated_at": "2026-04-21T00:00:00+00:00",
            },
        }

    monkeypatch.setattr(
        "backend.routers.workspace.save_workspace_snapshot",
        fake_save_workspace_snapshot,
    )

    response = client.post(
        "/api/workspace/save",
        headers={
            "X-Auth-Access-Token": "access-token",
            "X-Auth-Refresh-Token": "refresh-token",
        },
        json={
            "workspace_snapshot": {
                "candidate_profile": {"full_name": "Leander Antony"},
                "job_description": {"title": "Machine Learning Engineer"},
                "fit_analysis": {"overall_score": 82},
                "tailored_draft": {"target_role": "Machine Learning Engineer"},
                "artifacts": {},
            }
        },
    )

    assert response.status_code == 200
    assert captured["access_token"] == "access-token"
    assert captured["refresh_token"] == "refresh-token"
    assert captured["workspace_snapshot"]["job_description"]["title"] == "Machine Learning Engineer"


def test_workspace_saved_endpoint_returns_saved_snapshot(monkeypatch):
    monkeypatch.setattr(
        "backend.routers.workspace.load_saved_workspace_snapshot",
        lambda access_token, refresh_token: {
            "status": "available",
            "saved_workspace": {
                "job_title": "Machine Learning Engineer",
                "expires_at": "2026-04-22T00:00:00+00:00",
                "updated_at": "2026-04-21T00:00:00+00:00",
            },
            "workspace_snapshot": {
                "resume_document": {
                    "text": "resume text",
                    "filetype": "Saved Workspace",
                    "source": "saved_workspace",
                },
                "candidate_profile": {"full_name": "Leander Antony"},
                "job_description": {
                    "title": "Machine Learning Engineer",
                    "raw_text": "raw jd",
                    "cleaned_text": "cleaned jd",
                    "location": "Chennai",
                    "requirements": {
                        "hard_skills": ["Python"],
                        "soft_skills": ["Communication"],
                        "experience_requirement": "3+ years",
                        "must_haves": [],
                        "nice_to_haves": [],
                    },
                },
                "jd_summary_view": {"sections": [{"title": "Overview", "items": ["ML role"]}]},
                "fit_analysis": {
                    "target_role": "Machine Learning Engineer",
                    "overall_score": 82,
                    "readiness_label": "Strong",
                    "matched_hard_skills": ["Python"],
                    "missing_hard_skills": [],
                    "matched_soft_skills": ["Communication"],
                    "missing_soft_skills": [],
                    "experience_signal": "3+ years",
                    "strengths": ["Production Python"],
                    "gaps": [],
                    "recommendations": [],
                },
                "tailored_draft": {
                    "target_role": "Machine Learning Engineer",
                    "professional_summary": "summary",
                    "highlighted_skills": ["Python"],
                    "priority_bullets": ["Built ML APIs"],
                    "gap_mitigation_steps": [],
                },
                "agent_result": None,
                "artifacts": {
                    "tailored_resume": {
                        "title": "Tailored Resume",
                        "filename_stem": "tailored-resume",
                        "summary": "summary",
                        "markdown": "markdown",
                        "plain_text": "plain text",
                        "theme": "classic_ats",
                        "header": {
                            "full_name": "Leander Antony",
                            "location": "Chennai",
                            "contact_lines": [],
                        },
                        "target_role": "Machine Learning Engineer",
                        "professional_summary": "summary",
                        "highlighted_skills": ["Python"],
                        "experience_entries": [],
                        "education_entries": [],
                        "certifications": [],
                        "change_log": [],
                        "validation_notes": [],
                    },
                    "cover_letter": {
                        "title": "Cover Letter",
                        "filename_stem": "cover-letter",
                        "summary": "summary",
                        "markdown": "markdown",
                        "plain_text": "plain text",
                    },
                    "report": {
                        "title": "Report",
                        "filename_stem": "report",
                        "summary": "summary",
                        "markdown": "markdown",
                        "plain_text": "plain text",
                    },
                },
                "workflow": {
                    "mode": "saved_workspace",
                    "assisted_requested": False,
                    "assisted_available": True,
                    "review_approved": False,
                    "fallback_reason": "",
                },
                "imported_job_posting": None,
            },
        },
    )

    response = client.get(
        "/api/workspace/saved",
        headers={
            "X-Auth-Access-Token": "access-token",
            "X-Auth-Refresh-Token": "refresh-token",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "available"
    assert payload["workspace_snapshot"]["job_description"]["title"] == "Machine Learning Engineer"


def test_workspace_saved_jobs_endpoint_returns_shortlist(monkeypatch):
    monkeypatch.setattr(
        "backend.routers.workspace.list_saved_jobs",
        lambda access_token, refresh_token: {
            "status": "available",
            "saved_jobs": [
                {
                    "id": "job-123",
                    "title": "Machine Learning Engineer",
                    "company": "Example Labs",
                    "source": "greenhouse",
                    "location": "Chennai, India",
                    "employment_type": "Full-time",
                    "url": "https://example.com/jobs/job-123",
                    "summary": "Own production ML systems.",
                    "description_text": "Python SQL Docker",
                    "posted_at": "2026-04-20T10:00:00+00:00",
                    "scraped_at": "2026-04-21T10:00:00+00:00",
                    "metadata": {"departments": ["ML Platform"]},
                    "saved_at": "2026-04-21T10:05:00+00:00",
                    "updated_at": "2026-04-21T10:05:00+00:00",
                }
            ],
            "total_saved_jobs": 1,
            "latest_saved_at": "2026-04-21T10:05:00+00:00",
        },
    )

    response = client.get(
        "/api/workspace/saved-jobs",
        headers={
            "X-Auth-Access-Token": "access-token",
            "X-Auth-Refresh-Token": "refresh-token",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_saved_jobs"] == 1
    assert payload["saved_jobs"][0]["id"] == "job-123"


def test_workspace_saved_jobs_save_endpoint_forwards_auth_headers(monkeypatch):
    captured = {}

    def fake_save_saved_job(*, access_token, refresh_token, job_posting):
        captured["access_token"] = access_token
        captured["refresh_token"] = refresh_token
        captured["job_posting"] = job_posting
        return {
            "status": "saved",
            "saved_job": {
                **job_posting,
                "saved_at": "2026-04-21T10:05:00+00:00",
                "updated_at": "2026-04-21T10:05:00+00:00",
            },
            "message": "Saved Machine Learning Engineer to your shortlist.",
        }

    monkeypatch.setattr(
        "backend.routers.workspace.save_saved_job",
        fake_save_saved_job,
    )

    response = client.post(
        "/api/workspace/saved-jobs",
        headers={
            "X-Auth-Access-Token": "access-token",
            "X-Auth-Refresh-Token": "refresh-token",
        },
        json={
            "job_posting": {
                "id": "job-123",
                "title": "Machine Learning Engineer",
                "company": "Example Labs",
                "source": "greenhouse",
                "description_text": "Python SQL Docker",
                "metadata": {},
            }
        },
    )

    assert response.status_code == 200
    assert captured["access_token"] == "access-token"
    assert captured["refresh_token"] == "refresh-token"
    assert captured["job_posting"]["id"] == "job-123"


def test_workspace_saved_jobs_delete_endpoint_forwards_auth_headers(monkeypatch):
    captured = {}

    def fake_remove_saved_job(*, access_token, refresh_token, job_id):
        captured["access_token"] = access_token
        captured["refresh_token"] = refresh_token
        captured["job_id"] = job_id
        return {
            "status": "removed",
            "job_id": job_id,
        }

    monkeypatch.setattr(
        "backend.routers.workspace.remove_saved_job",
        fake_remove_saved_job,
    )

    response = client.delete(
        "/api/workspace/saved-jobs/job-123",
        headers={
            "X-Auth-Access-Token": "access-token",
            "X-Auth-Refresh-Token": "refresh-token",
        },
    )

    assert response.status_code == 200
    assert captured["access_token"] == "access-token"
    assert captured["refresh_token"] == "refresh-token"
    assert captured["job_id"] == "job-123"


def test_workspace_artifact_export_endpoint_forwards_snapshot(monkeypatch):
    captured = {}

    def fake_export_workspace_artifact(*, workspace_snapshot, artifact_kind, export_format, resume_theme):
        captured["workspace_snapshot"] = workspace_snapshot
        captured["artifact_kind"] = artifact_kind
        captured["export_format"] = export_format
        captured["resume_theme"] = resume_theme
        return {
            "status": "ready",
            "artifact_kind": artifact_kind,
            "export_format": export_format,
            "file_name": "leander-antony-machine-learning-engineer-tailored-resume.pdf",
            "mime_type": "application/pdf",
            "content_base64": "cGRm",
            "resume_theme": resume_theme,
            "artifact_title": "Leander Antony - Machine Learning Engineer Tailored Resume",
        }

    monkeypatch.setattr(
        "backend.routers.workspace.export_workspace_artifact",
        fake_export_workspace_artifact,
    )

    response = client.post(
        "/api/workspace/artifacts/export",
        json={
            "workspace_snapshot": {
                "candidate_profile": {"full_name": "Leander Antony"},
                "job_description": {"title": "Machine Learning Engineer"},
                "fit_analysis": {"overall_score": 82},
                "tailored_draft": {"target_role": "Machine Learning Engineer"},
            },
            "artifact_kind": "tailored_resume",
            "export_format": "pdf",
            "resume_theme": "classic_ats",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert captured["artifact_kind"] == "tailored_resume"
    assert captured["export_format"] == "pdf"
    assert captured["resume_theme"] == "classic_ats"


def test_workspace_artifact_preview_endpoint_forwards_snapshot(monkeypatch):
    captured = {}

    def fake_preview_workspace_artifact(*, workspace_snapshot, artifact_kind, resume_theme):
        captured["workspace_snapshot"] = workspace_snapshot
        captured["artifact_kind"] = artifact_kind
        captured["resume_theme"] = resume_theme
        return {
            "status": "ready",
            "artifact_kind": artifact_kind,
            "resume_theme": resume_theme,
            "artifact_title": "Leander Antony - Machine Learning Engineer Tailored Resume",
            "html": "<html><body><h1>Preview</h1></body></html>",
        }

    monkeypatch.setattr(
        "backend.routers.workspace.preview_workspace_artifact",
        fake_preview_workspace_artifact,
    )

    response = client.post(
        "/api/workspace/artifacts/preview",
        json={
            "workspace_snapshot": {
                "candidate_profile": {"full_name": "Leander Antony"},
                "job_description": {"title": "Machine Learning Engineer"},
                "fit_analysis": {"overall_score": 82},
                "tailored_draft": {"target_role": "Machine Learning Engineer"},
            },
            "artifact_kind": "tailored_resume",
            "resume_theme": "classic_ats",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["artifact_kind"] == "tailored_resume"
    assert captured["resume_theme"] == "classic_ats"
