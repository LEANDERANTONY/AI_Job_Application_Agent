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
