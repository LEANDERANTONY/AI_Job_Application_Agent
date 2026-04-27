from backend.services.artifact_export_service import preview_workspace_artifact
from src.workflow_payloads import build_saved_workflow_snapshot_from_data


def _malformed_workspace_snapshot():
    return {
        "candidate_profile": {
            "full_name": "Leander Antony",
            "location": "Chennai",
            "contact_lines": ["leander@example.com"],
            "source": "workspace",
            "resume_text": "Resume text",
            "skills": ["Python", "FastAPI"],
            "experience": [
                {
                    "title": "Engineer",
                    "organization": "Example Corp",
                    "location": "Remote",
                    "description": "Built features",
                    "start": "2023",
                    "end": "2024",
                },
                "unexpected-string-entry",
            ],
            "education": [None],
            "certifications": [],
            "source_signals": [],
        },
        "job_description": {
            "title": "ML Engineer",
            "raw_text": "We need Python and FastAPI experience.",
            "cleaned_text": "We need Python and FastAPI experience.",
            "location": "Remote",
            "requirements": {
                "hard_skills": ["Python", "FastAPI"],
                "soft_skills": ["Communication"],
                "experience_requirement": "3+ years",
                "must_haves": ["APIs"],
                "nice_to_haves": ["LLMs"],
            },
        },
        "fit_analysis": {
            "target_role": "ML Engineer",
            "overall_score": 82,
            "readiness_label": "Strong",
            "matched_hard_skills": ["Python"],
            "missing_hard_skills": ["Kubernetes"],
            "matched_soft_skills": ["Communication"],
            "missing_soft_skills": [],
            "experience_signal": "Relevant backend work",
            "strengths": ["API design"],
            "gaps": ["Kubernetes"],
            "recommendations": ["Highlight deployment work"],
        },
        "tailored_draft": {
            "target_role": "ML Engineer",
            "professional_summary": "Backend engineer focused on ML tooling.",
            "highlighted_skills": ["Python", "FastAPI"],
            "priority_bullets": ["Built APIs for AI workflows"],
            "gap_mitigation_steps": ["Call out transferable infra work"],
        },
        "agent_result": {
            "mode": "agentic",
            "model": "gpt-test",
            "profile": {"positioning_headline": "ML engineer", "evidence_highlights": [], "strengths": [], "cautions": []},
            "job": {"requirement_summary": "Python-heavy role", "priority_skills": [], "must_have_themes": [], "messaging_guidance": []},
            "fit": {"fit_summary": "Good fit", "top_matches": [], "key_gaps": []},
            "tailoring": {
                "professional_summary": "Backend engineer focused on ML tooling.",
                "rewritten_bullets": ["Built APIs for AI workflows"],
                "highlighted_skills": ["Python", "FastAPI"],
                "cover_letter_themes": ["ownership"],
            },
            "review": {
                "approved": True,
                "grounding_issues": [],
                "unresolved_issues": [],
                "revision_requests": [],
                "final_notes": [],
            },
            "review_history": [None, "unexpected-review-entry"],
        },
        "imported_job_posting": None,
    }


def test_build_saved_workflow_snapshot_tolerates_malformed_nested_items():
    snapshot = build_saved_workflow_snapshot_from_data(_malformed_workspace_snapshot())

    assert snapshot is not None
    assert snapshot.candidate_profile.experience[1].title == ""
    assert snapshot.candidate_profile.education[0].institution == ""
    assert snapshot.agent_result is not None
    assert snapshot.agent_result.review_history[0].pass_index == 0
    assert snapshot.agent_result.review_history[1].pass_index == 0


def test_preview_workspace_artifact_tolerates_malformed_nested_items():
    response = preview_workspace_artifact(
        workspace_snapshot=_malformed_workspace_snapshot(),
        artifact_kind="tailored_resume",
        resume_theme="classic_ats",
    )

    assert response["status"] == "ready"
    assert "<html" in response["html"].lower()
