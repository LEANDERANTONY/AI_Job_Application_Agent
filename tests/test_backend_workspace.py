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


def test_resume_builder_message_uses_llm_when_openai_service_available(monkeypatch):
    """LLM-first intake: when an OpenAIService is plumbed in, the
    model picks the next question and merges partial draft updates,
    instead of marching through the hardcoded 5 steps."""
    from backend.services.resume_builder_service import _SESSIONS

    captured_prompts: list[dict] = []

    class _StubOpenAIService:
        def is_available(self):
            return True

        def run_json_prompt(self, system, user, **kwargs):
            captured_prompts.append({"system": system, "user": user})
            return {
                "draft_updates": {
                    "full_name": "Leander Antony",
                    "location": "Chennai, India",
                    "contact_lines": ["leander@example.com", "+91 9999999999"],
                },
                "assistant_message": (
                    "Got it — Leander Antony in Chennai. What role are you "
                    "targeting?"
                ),
                "status": "collecting",
                "focus_field": "target_role",
            }

    monkeypatch.setattr(
        "backend.routers.workspace._resolve_openai_service",
        lambda access_token, refresh_token: _StubOpenAIService(),
    )

    start = client.post("/api/workspace/resume-builder/start")
    session_id = start.json()["session_id"]

    response = client.post(
        "/api/workspace/resume-builder/message",
        json={
            "session_id": session_id,
            "message": "I'm Leander Antony, based in Chennai, India. Reach me at leander@example.com or +91 9999999999.",
            "input_mode": "text",
        },
        headers={
            "X-Auth-Access-Token": "access-token",
            "X-Auth-Refresh-Token": "refresh-token",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["draft_profile"]["full_name"] == "Leander Antony"
    assert payload["draft_profile"]["location"] == "Chennai, India"
    assert "leander@example.com" in payload["draft_profile"]["contact_lines"]
    # Assistant message comes from the LLM, not the hardcoded step
    # acknowledgements.
    assert "Leander Antony" in payload["assistant_message"]
    # Only one LLM call; no regex step machine fallback ran.
    assert len(captured_prompts) == 1
    # The prompt body contains the user's literal message + the
    # current draft state so the model can ground its updates.
    assert "Leander Antony" in captured_prompts[0]["user"]

    # The session's conversation_history should now have one
    # user/assistant pair so subsequent turns have continuity.
    session = _SESSIONS[session_id]
    assert len(session.conversation_history) == 2
    assert session.conversation_history[0]["role"] == "user"
    assert session.conversation_history[1]["role"] == "assistant"


def test_resume_builder_message_falls_back_to_regex_when_llm_errors(monkeypatch):
    """When the LLM raises (no key, malformed JSON, network error, etc.),
    the deterministic regex step machine still runs so the feature
    keeps working."""
    from backend.services.resume_builder_service import _SESSIONS
    from src.errors import AgentExecutionError

    class _BrokenOpenAIService:
        def is_available(self):
            return True

        def run_json_prompt(self, system, user, **kwargs):
            raise AgentExecutionError("Simulated LLM failure for test.")

    monkeypatch.setattr(
        "backend.routers.workspace._resolve_openai_service",
        lambda access_token, refresh_token: _BrokenOpenAIService(),
    )

    start = client.post("/api/workspace/resume-builder/start")
    session_id = start.json()["session_id"]

    response = client.post(
        "/api/workspace/resume-builder/message",
        json={
            "session_id": session_id,
            "message": "Leander Antony, Chennai, leander@example.com",
            "input_mode": "text",
        },
        headers={
            "X-Auth-Access-Token": "access-token",
            "X-Auth-Refresh-Token": "refresh-token",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    # Regex fallback fired: full_name + contact captured by
    # _apply_basics, current_step advanced to "role".
    assert payload["draft_profile"]["full_name"] == "Leander Antony"
    assert payload["current_step"] == "role"
    # Conversation history stays empty because the LLM path errored
    # before the user/assistant pair could be appended.
    assert _SESSIONS[session_id].conversation_history == []


def test_resume_builder_message_handles_backtracking_via_llm(monkeypatch):
    """Mid-flow correction: user says 'actually my role is X' on turn 2,
    LLM returns target_role=X in draft_updates, and the new value
    overwrites the prior one."""
    from backend.services.resume_builder_service import _SESSIONS

    turns: list[dict] = [
        {
            "draft_updates": {"target_role": "ML Engineer"},
            "assistant_message": "Got it — ML Engineer. What's your most relevant experience?",
            "status": "collecting",
            "focus_field": "experience_notes",
        },
        {
            "draft_updates": {"target_role": "Senior ML Engineer"},
            "assistant_message": "Updated to Senior ML Engineer. Tell me about your most relevant role.",
            "status": "collecting",
            "focus_field": "experience_notes",
        },
    ]
    turn_index = {"value": 0}

    class _StubOpenAIService:
        def is_available(self):
            return True

        def run_json_prompt(self, system, user, **kwargs):
            payload = turns[turn_index["value"]]
            turn_index["value"] += 1
            return payload

    monkeypatch.setattr(
        "backend.routers.workspace._resolve_openai_service",
        lambda access_token, refresh_token: _StubOpenAIService(),
    )

    start = client.post("/api/workspace/resume-builder/start")
    session_id = start.json()["session_id"]
    auth_headers = {
        "X-Auth-Access-Token": "access-token",
        "X-Auth-Refresh-Token": "refresh-token",
    }

    first = client.post(
        "/api/workspace/resume-builder/message",
        json={"session_id": session_id, "message": "I'm targeting an ML Engineer role.", "input_mode": "text"},
        headers=auth_headers,
    )
    assert first.json()["draft_profile"]["target_role"] == "ML Engineer"

    second = client.post(
        "/api/workspace/resume-builder/message",
        json={
            "session_id": session_id,
            "message": "Actually, I should aim for Senior ML Engineer.",
            "input_mode": "text",
        },
        headers=auth_headers,
    )
    # The corrected role overwrote the earlier one.
    assert second.json()["draft_profile"]["target_role"] == "Senior ML Engineer"
    # Conversation history has both turn pairs.
    assert len(_SESSIONS[session_id].conversation_history) == 4


def test_resume_builder_message_recovers_session_after_cache_miss(monkeypatch):
    """Container restart wipes `_SESSIONS`, but the draft is in Supabase.
    Mutating routes lazy-load from the store before returning the
    existing 400 — verify the recovery path actually round-trips."""
    from backend.services.resume_builder_service import (
        _SESSIONS,
        export_resume_builder_session_payload,
    )
    from src.schemas import ResumeBuilderSessionRecord

    start_response = client.post("/api/workspace/resume-builder/start")
    assert start_response.status_code == 200
    session_id = start_response.json()["session_id"]

    seed_response = client.post(
        "/api/workspace/resume-builder/message",
        json={
            "session_id": session_id,
            "message": "Leander Antony\nChennai, India\nleander@example.com",
            "input_mode": "text",
        },
    )
    assert seed_response.status_code == 200
    assert seed_response.json()["current_step"] == "role"

    captured_payload = export_resume_builder_session_payload(session_id=session_id)

    _SESSIONS.clear()
    assert session_id not in _SESSIONS

    class _FakeAppUser:
        id = "user-1"

    class _FakeContext:
        app_user = _FakeAppUser()

    class _FakeStore:
        def load_latest_session(self, access, refresh, user_id):
            return ResumeBuilderSessionRecord(
                user_id=user_id,
                session_id=session_id,
                status="collecting",
                current_step="role",
                session_payload_json=captured_payload,
                updated_at="",
            )

        def save_session(self, access, refresh, payload):
            return ResumeBuilderSessionRecord(
                user_id=payload["user_id"],
                session_id=payload["session_id"],
                status="",
                current_step="",
                session_payload_json=payload["session_payload_json"],
                updated_at="",
            )

    monkeypatch.setattr(
        "backend.services.resume_builder_persistence_service._resolve_store",
        lambda access_token, refresh_token: (_FakeContext(), _FakeStore()),
    )

    recovered_response = client.post(
        "/api/workspace/resume-builder/message",
        json={
            "session_id": session_id,
            "message": "Machine Learning Engineer. AI engineer with applied AI experience.",
            "input_mode": "text",
        },
        headers={
            "X-Auth-Access-Token": "access-token",
            "X-Auth-Refresh-Token": "refresh-token",
        },
    )

    assert recovered_response.status_code == 200
    payload = recovered_response.json()
    assert payload["current_step"] == "experience"
    assert payload["draft_profile"]["target_role"] == "Machine Learning Engineer"


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


def test_workspace_analyze_job_start_returns_job_handle(monkeypatch):
    monkeypatch.setattr(
        "backend.routers.workspace.start_workspace_analysis_job",
        lambda **kwargs: {
            "job_id": "job-123",
            "status": "queued",
            "stage_title": "Workflow crew",
            "stage_detail": "Preparing the first agent.",
            "progress_percent": 3,
            "result": None,
            "error_message": None,
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
    assert payload["result"] is None
    assert payload["error_message"] is None


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


def test_workspace_analyze_job_start_returns_503_when_capacity_exhausted(monkeypatch):
    """When all concurrent run slots are taken, the start endpoint must
    fast-fail with 503 + Retry-After instead of queueing the request
    behind a thread spawn or returning a generic 500."""
    from backend.services.workspace_run_jobs import WorkspaceRunJobCapacityError

    def _raise_capacity(**_kwargs):
        raise WorkspaceRunJobCapacityError(
            "Too many agentic workflow runs are in flight right now."
        )

    monkeypatch.setattr(
        "backend.routers.workspace.start_workspace_analysis_job",
        _raise_capacity,
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

    assert response.status_code == 503
    assert response.headers.get("Retry-After")
    assert int(response.headers["Retry-After"]) > 0
    assert "busy" in response.json()["detail"].lower()


def test_workspace_analyze_job_status_returns_actionable_404_when_job_missing(monkeypatch):
    """Container restart drops `_JOBS`. The poll-side response should
    explain the cause and prompt a re-run, not return a bare
    'not found' that the hook surfaces unchanged."""
    monkeypatch.setattr(
        "backend.routers.workspace.get_workspace_analysis_job",
        lambda job_id: None,
    )

    response = client.get("/api/workspace/analyze-jobs/missing-job-id")

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "no longer available" in detail.lower()
    assert "run the workflow again" in detail.lower()


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
    assert "Staff Software Engineer, Machine Learning" in payload["artifacts"]["cover_letter"]["title"]
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


def test_workspace_signature_is_stable_64_char_hash():
    """`workflow_signature` is the change-detection fingerprint stored
    on every saved-workspace row. Pin: it's 64 chars (sha256 hex) and
    deterministic across runs for the same canonical payload."""
    from backend.services.workspace_persistence_service import _workspace_signature

    snapshot = {
        "candidate_profile": {"full_name": "Leander Antony", "skills": ["Python", "AWS"]},
        "job_description": {"title": "Senior ML Engineer"},
        "fit_analysis": {"overall_score": 55, "matched_hard_skills": ["Python"]},
        "tailored_draft": {"target_role": "Senior ML Engineer"},
        # extra keys the signature must ignore
        "artifacts": {"tailored_resume": {"markdown": "# Resume"}},
        "agent_result": {"mode": "openai"},
    }

    signature = _workspace_signature(snapshot)

    assert isinstance(signature, str)
    assert len(signature) == 64
    assert all(c in "0123456789abcdef" for c in signature)

    # Same canonical payload → same hash. Re-ordering keys shouldn't
    # change the result because `json.dumps(sort_keys=True)` is the
    # canonicalization step.
    snapshot_reordered = dict(reversed(list(snapshot.items())))
    assert _workspace_signature(snapshot_reordered) == signature

    # Adding/changing a tracked field DOES change the hash.
    mutated = dict(snapshot)
    mutated["candidate_profile"] = {**snapshot["candidate_profile"], "skills": ["Python"]}
    assert _workspace_signature(mutated) != signature

    # Adding/changing an UNTRACKED field doesn't (artifacts, agent_result
    # aren't in the canonical payload).
    untracked = dict(snapshot)
    untracked["artifacts"] = {"tailored_resume": {"markdown": "# Different"}}
    assert _workspace_signature(untracked) == signature


def test_workspace_save_then_load_round_trips_artifact_markdown(monkeypatch):
    """The save/load round-trip should preserve the rendered tailored
    resume + cover letter markdown exactly. Container restarts (saved
    sessions outliving in-memory state) rely on this — if any field
    in the snapshot drops on serialize or fails to rehydrate, the
    user sees a different document than they saved."""
    from types import SimpleNamespace

    from backend.services import workspace_persistence_service
    from src.schemas import SavedWorkspaceRecord
    from src.services.fit_service import build_fit_analysis
    from src.services.job_service import build_job_description_from_text
    from src.services.profile_service import build_candidate_profile_from_resume
    from src.services.tailoring_service import build_tailored_resume_draft
    from src.resume_builder import build_tailored_resume_artifact
    from src.cover_letter_builder import build_cover_letter_artifact
    from src.schemas import ResumeDocument

    # Build a realistic snapshot deterministically (no LLM cost) so the
    # round-trip has substantive payload to preserve.
    resume_text = (
        "Leander Antony\n"
        "Chennai, India\n"
        "leander@example.com\n"
        "+91 9999999999\n"
        "Skills: Python, FastAPI, Docker, SQL, AWS\n"
        "Experience\n"
        "AI Engineer at Example Labs (Jan 2023 - Present)\n"
        "Built ML evaluation pipelines.\n"
        "Education\n"
        "Anna University, B.E. Computer Science\n"
    )
    jd_text = (
        "Senior ML Engineer\n"
        "Required: Python, AWS, SQL.\n"
        "Need 5+ years.\n"
    )
    candidate_profile = build_candidate_profile_from_resume(
        ResumeDocument(text=resume_text, filetype="TXT", source="test")
    )
    job_description = build_job_description_from_text(jd_text)
    fit_analysis = build_fit_analysis(candidate_profile, job_description)
    tailored_draft = build_tailored_resume_draft(
        candidate_profile, job_description, fit_analysis
    )
    tailored_resume = build_tailored_resume_artifact(
        candidate_profile, job_description, fit_analysis, tailored_draft
    )
    cover_letter = build_cover_letter_artifact(
        candidate_profile, job_description, fit_analysis, tailored_draft
    )

    # Snapshot shape mirrors what `run_workspace_analysis` produces.
    workspace_snapshot = {
        "candidate_profile": _to_serializable(candidate_profile),
        "job_description": _to_serializable(job_description),
        "fit_analysis": _to_serializable(fit_analysis),
        "tailored_draft": _to_serializable(tailored_draft),
        "agent_result": None,
        "imported_job_posting": None,
        "artifacts": {
            "tailored_resume": _to_serializable(tailored_resume),
            "cover_letter": _to_serializable(cover_letter),
        },
    }

    # In-memory mock store. Records are keyed by user_id and survive
    # the "session restart" — this is the fixture for verifying the
    # round-trip.
    storage: dict[str, dict] = {}

    class _MockStore:
        def __init__(self, *_args, **_kwargs):
            pass

        def is_configured(self):
            return True

        def save_workspace(self, access_token, refresh_token, payload):
            user_id = payload["user_id"]
            record = SavedWorkspaceRecord(
                user_id=user_id,
                job_title=payload["job_title"],
                workflow_signature=payload["workflow_signature"],
                workflow_snapshot_json=payload["workflow_snapshot_json"],
                cover_letter_payload_json=payload["cover_letter_payload_json"],
                tailored_resume_payload_json=payload["tailored_resume_payload_json"],
                expires_at="2099-01-01T00:00:00+00:00",
                updated_at="2026-05-07T12:00:00+00:00",
            )
            # Capture exactly what was persisted — this is the source
            # of truth the load path will rehydrate from.
            storage[user_id] = {
                "record": record,
                "raw_payload": dict(payload),
            }
            return record

        def load_workspace(self, access_token, refresh_token, user_id, now=None):
            entry = storage.get(user_id)
            if entry is None:
                return None, "missing"
            return entry["record"], "available"

    fake_context = SimpleNamespace(
        app_user=SimpleNamespace(id="test-user"),
        auth_service=SimpleNamespace(is_configured=lambda: True),
    )

    monkeypatch.setattr(
        workspace_persistence_service,
        "resolve_authenticated_context",
        lambda *, access_token, refresh_token: fake_context,
    )
    monkeypatch.setattr(
        workspace_persistence_service,
        "SavedWorkspaceStore",
        _MockStore,
    )

    save_response = workspace_persistence_service.save_workspace_snapshot(
        access_token="access-token",
        refresh_token="refresh-token",
        workspace_snapshot=workspace_snapshot,
    )
    assert save_response["status"] == "saved"
    assert save_response["saved_workspace"]["job_title"] == "Senior ML Engineer"

    # Simulate "session expiry": local in-memory state is gone, but
    # the DB record persists. The load endpoint pulls from storage
    # and re-renders the artifacts from the saved snapshot.
    load_response = workspace_persistence_service.load_saved_workspace_snapshot(
        access_token="access-token",
        refresh_token="refresh-token",
    )
    assert load_response["status"] == "available"

    rehydrated_snapshot = load_response["workspace_snapshot"]
    rehydrated_resume = rehydrated_snapshot["artifacts"]["tailored_resume"]
    rehydrated_cover_letter = rehydrated_snapshot["artifacts"]["cover_letter"]

    # Markdown is the user-visible payload — these must match exactly.
    assert rehydrated_resume["markdown"] == tailored_resume.markdown
    assert rehydrated_cover_letter["markdown"] == cover_letter.markdown
    # Title and filename_stem flow through the saved payload to the
    # re-rendered artifact. Mismatches here mean the export filename
    # would change between save and reload.
    assert rehydrated_resume["title"] == tailored_resume.title
    assert rehydrated_resume["filename_stem"] == tailored_resume.filename_stem
    assert rehydrated_cover_letter["title"] == cover_letter.title

    # Candidate identity round-trips byte-equal — name + email + skills
    # are the irreducible parts a recruiter sees.
    rehydrated_profile = rehydrated_snapshot["candidate_profile"]
    assert rehydrated_profile["full_name"] == candidate_profile.full_name
    assert rehydrated_profile["contact_lines"] == candidate_profile.contact_lines
    assert rehydrated_profile["skills"] == candidate_profile.skills
    # JD title round-trips so the saved-workspaces sidebar label stays
    # accurate after reload.
    assert rehydrated_snapshot["job_description"]["title"] == job_description.title


def _to_serializable(value):
    """Inline dataclass -> dict helper. Mirrors the persistence
    service's `_serialize` so the test doesn't import a private."""
    from dataclasses import asdict, is_dataclass

    if is_dataclass(value):
        return {k: _to_serializable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _to_serializable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_serializable(item) for item in value]
    return value


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

    def fake_export_workspace_artifact(
        *, workspace_snapshot, artifact_kind, export_format, resume_theme, cover_letter_theme
    ):
        captured["workspace_snapshot"] = workspace_snapshot
        captured["artifact_kind"] = artifact_kind
        captured["export_format"] = export_format
        captured["resume_theme"] = resume_theme
        captured["cover_letter_theme"] = cover_letter_theme
        return {
            "status": "ready",
            "artifact_kind": artifact_kind,
            "export_format": export_format,
            "file_name": "leander-antony-machine-learning-engineer-tailored-resume.pdf",
            "mime_type": "application/pdf",
            "content_base64": "cGRm",
            "resume_theme": resume_theme,
            "cover_letter_theme": cover_letter_theme,
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

    def fake_preview_workspace_artifact(
        *, workspace_snapshot, artifact_kind, resume_theme, cover_letter_theme
    ):
        captured["workspace_snapshot"] = workspace_snapshot
        captured["artifact_kind"] = artifact_kind
        captured["resume_theme"] = resume_theme
        captured["cover_letter_theme"] = cover_letter_theme
        return {
            "status": "ready",
            "artifact_kind": artifact_kind,
            "resume_theme": resume_theme,
            "cover_letter_theme": cover_letter_theme,
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
