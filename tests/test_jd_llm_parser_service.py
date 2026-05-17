from src.services.jd_llm_parser_service import JobDescriptionLLMParserService


class _RecordingOpenAIService:
    """Captures the run_json_prompt kwargs so we can assert the JD
    parser asks for enough output budget + keeps the retry net."""

    def __init__(self):
        self.kwargs = None

    def is_available(self):
        return True

    def run_json_prompt(self, *args, **kwargs):
        self.kwargs = kwargs
        return {
            "title": "AI Engineer",
            "location": "",
            "salary": "",
            "experience_requirement": "",
            "hard_skills": [],
            "soft_skills": [],
            "must_haves": [],
            "nice_to_haves": [],
        }


def test_jd_parser_requests_generous_budget_and_enables_retry():
    """Regression (mirror of the resume-parser fix): a detailed JD
    (full responsibilities + a long hard-skill list + must/nice-to-
    haves) truncated the JSON under a tight cap with budget-retry
    disabled, so build_job_description_from_text_auto silently fell
    back to the lower-fidelity deterministic JD parser. That degraded
    JD then feeds fit analysis, tailoring, and the cover letter — the
    truncation cascades. The parser must request a generous ceiling
    AND keep the auto-retry safety net."""
    recorder = _RecordingOpenAIService()
    service = JobDescriptionLLMParserService(openai_service=recorder)

    service.parse("Senior AI Engineer — lots of requirements ...")

    assert recorder.kwargs is not None
    assert recorder.kwargs["max_completion_tokens"] >= 4000
    assert recorder.kwargs["allow_output_budget_retry"] is True
