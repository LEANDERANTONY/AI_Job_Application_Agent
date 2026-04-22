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
            "file_name": "leander-antony-machine-learning-engineer-tailored-resume-modern_professional.pdf",
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
            "resume_theme": "modern_professional",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert captured["artifact_kind"] == "tailored_resume"
    assert captured["export_format"] == "pdf"
    assert captured["resume_theme"] == "modern_professional"


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
            "resume_theme": "modern_professional",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["artifact_kind"] == "tailored_resume"
    assert captured["resume_theme"] == "modern_professional"
