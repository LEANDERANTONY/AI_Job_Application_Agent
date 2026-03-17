from src.prompts import (
    build_assistant_prompt,
    build_application_qa_assistant_prompt,
    build_fit_agent_prompt,
    build_review_agent_prompt,
    build_strategy_agent_prompt,
)


def test_fit_prompt_compacts_large_sections_and_emits_budget_metadata():
    candidate_profile = {
        "summary": "A" * 5000,
        "experience": [
            {
                "title": "Engineer",
                "description": "B" * 3000,
            }
            for _ in range(10)
        ],
    }
    job_description = {
        "title": "Data Scientist",
        "responsibilities": ["C" * 1200 for _ in range(8)],
    }
    fit_analysis = {
        "overall_score": 78,
        "strengths": ["D" * 900 for _ in range(6)],
        "gaps": ["E" * 900 for _ in range(6)],
    }
    prompt = build_fit_agent_prompt(
        candidate_profile,
        job_description,
        fit_analysis,
    )

    assert int(prompt["metadata"]["estimated_input_chars"]) == len(prompt["user"])
    assert prompt["metadata"]["prompt_budget_mode"] == "compacted"
    assert int(prompt["metadata"]["compacted_sections"]) >= 1
    assert "Candidate Profile" in prompt["metadata"].get("compacted_labels", "")
    assert len(prompt["user"]) < 15000


def test_application_qa_prompt_allows_grounded_general_coaching():
    prompt = build_application_qa_assistant_prompt(
        workflow_context={"candidate_profile": {"summary": "Built dashboards"}},
        question="How do I show collaboration without formal experience?",
    )

    assert "broader resume or application coaching" in prompt["system"]
    assert "general advice" in prompt["system"]


def test_unified_assistant_prompt_mentions_retrieved_knowledge_hits_and_cover_letter():
    prompt = build_assistant_prompt(
        assistant_context={
            "current_page": "Manual JD Input",
            "product_context": {"knowledge_hits": [{"source": "Cover Letter"}]},
            "workflow_context": {"has_cover_letter": True},
        },
        question="How does the cover letter fit into this flow?",
    )

    assert "retrieved product knowledge hits" in prompt["system"]
    assert "cover letter" in prompt["system"].lower()
    assert "Assistant Context" in prompt["user"]


def test_strategy_prompt_uses_current_grounded_sections_only():
    prompt = build_strategy_agent_prompt(
        candidate_profile={"education": [{"degree": "Master of Science in AI/ML"}]},
        job_description={"title": "ML Engineer"},
        fit_analysis={"gaps": ["SQL"]},
        fit_output={"top_matches": ["Python", "XGBoost"]},
        tailoring_output={"professional_summary": "Project-focused summary."},
    )

    assert "Tailoring Agent Output" in prompt["user"]
    assert "Fit Agent Output" in prompt["user"]
    assert "Previous Strategy Output" not in prompt["user"]
    assert "Revision Requests" not in prompt["user"]


def test_review_prompt_allows_null_corrections_when_no_rewrite_is_needed():
    prompt = build_review_agent_prompt(
        candidate_profile={"summary": "Built dashboards and ML pipelines."},
        job_description={"title": "ML Engineer"},
        fit_analysis={"strengths": ["Python"]},
        tailored_draft={"professional_summary": "Grounded draft."},
        tailoring_output={"professional_summary": "Grounded summary."},
        strategy_output={"recruiter_positioning": "Grounded positioning."},
    )

    assert "Return null for corrected_tailoring and corrected_strategy" in prompt["system"]
    assert "null when no tailoring changes are needed" in prompt["system"]
    assert "null when no strategy changes are needed" in prompt["system"]
    assert "unresolved_issues" in prompt["system"]
    assert "Approve when the final corrected wording stays grounded" in prompt["system"]