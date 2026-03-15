from src.prompts import build_fit_agent_prompt


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
    profile_output = {"evidence_highlights": ["F" * 800 for _ in range(5)]}
    job_output = {"priority_skills": ["G" * 800 for _ in range(5)]}

    prompt = build_fit_agent_prompt(
        candidate_profile,
        job_description,
        fit_analysis,
        profile_output,
        job_output,
    )

    assert int(prompt["metadata"]["estimated_input_chars"]) == len(prompt["user"])
    assert prompt["metadata"]["prompt_budget_mode"] == "compacted"
    assert int(prompt["metadata"]["compacted_sections"]) >= 1
    assert "Candidate Profile" in prompt["metadata"].get("compacted_labels", "")
    assert len(prompt["user"]) < 15000