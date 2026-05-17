from src.schemas import ResumeDocument
from src.services.resume_llm_parser_service import ResumeLLMParserService
from tests.test_openai_service import FakeClient, _build_response


def test_resume_llm_parser_service_normalizes_payload():
    client = FakeClient(
        [
            _build_response(
                """
                {
                  "full_name": "Leander Antony A",
                  "location": "Chennai, India",
                  "contact_lines": ["leander@example.com", "https://github.com/leander", "https://github.com/leander"],
                  "summary": "ML engineer with project-heavy resume.",
                  "skills": ["Python", "Python", "FastAPI"],
                  "experience": [
                    {
                      "title": "ML Engineer",
                      "organization": "Independent",
                      "location": "",
                      "start": "2024",
                      "end": "Present",
                      "description": "Built production AI tools."
                    }
                  ],
                  "projects": [
                    {
                      "title": "HelpMate AI",
                      "organization": "",
                      "start": "",
                      "end": "",
                      "description": "Grounded RAG project.",
                      "links": ["https://github.com/example/helpmate"]
                    }
                  ],
                  "education": [
                    {
                      "institution": "Liverpool John Moores University",
                      "degree": "MSc",
                      "field_of_study": "Machine Learning",
                      "start": "2024",
                      "end": "2025"
                    }
                  ],
                  "certifications": ["AWS Certified"],
                  "publications": ["Antony, L. (2024). Sample paper. Sample Conf 2024."],
                  "source_signals": ["Projects section found"]
                }
                """.strip()
            )
        ]
    )
    service = ResumeLLMParserService(openai_service=None)
    service._openai_service = type(service._openai_service)(client=client) if service._openai_service else None
    if service._openai_service is None:
        from src.openai_service import OpenAIService

        service._openai_service = OpenAIService(client=client)

    payload = service.parse(
        ResumeDocument(text="Sample resume text", filetype="DOCX", source="uploaded")
    )

    assert payload["full_name"] == "Leander Antony A"
    assert payload["skills"] == ["Python", "FastAPI"]
    assert payload["contact_lines"] == [
        "leander@example.com",
        "https://github.com/leander",
    ]
    assert payload["experience"][0]["title"] == "ML Engineer"
    assert payload["projects"][0]["title"] == "HelpMate AI"
    assert payload["education"][0]["institution"] == "Liverpool John Moores University"


class _RecordingOpenAIService:
    """Captures the run_json_prompt kwargs so we can assert the
    resume parser asks for enough output budget + the retry net."""

    def __init__(self):
        self.kwargs = None

    def is_available(self):
        return True

    def run_json_prompt(self, *args, **kwargs):
        self.kwargs = kwargs
        return {
            "full_name": "Test",
            "location": "",
            "contact_lines": [],
            "summary": "",
            "skills": [],
            "experience": [],
            "projects": [],
            "education": [],
            "certifications": [],
            "publications": [],
            "source_signals": [],
        }


def test_resume_parser_requests_generous_budget_and_enables_retry():
    """Regression: a 2600-token cap with budget-retry disabled
    truncated the JSON for content-rich resumes ~2 of 3 times, forcing
    the low-fidelity deterministic fallback (garbled project names,
    project URLs leaking into the contact line). The parser must ask
    for a generous ceiling AND keep the auto-retry safety net."""
    recorder = _RecordingOpenAIService()
    service = ResumeLLMParserService(openai_service=recorder)

    service.parse(
        ResumeDocument(text="Sample resume text", filetype="DOCX", source="uploaded")
    )

    assert recorder.kwargs is not None
    assert recorder.kwargs["max_completion_tokens"] >= 6000
    assert recorder.kwargs["allow_output_budget_retry"] is True
