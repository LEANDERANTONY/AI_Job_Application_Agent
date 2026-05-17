from src.errors import AgentExecutionError, OpenAIUnavailableError
from src.services.job_service import build_job_description_from_text
from src.services.jd_summary_service import generate_job_summary_view


class _OutageOpenAI:
    def __init__(self, exc):
        self._exc = exc

    @staticmethod
    def is_available():
        return True

    def run_structured_prompt(self, *args, **kwargs):
        raise self._exc


def _jd():
    return build_job_description_from_text(
        "Backend Engineer\nRequired: Python, SQL, APIs.\nNeed 3+ years.\n"
    )


def test_jd_summary_attaches_service_notice_on_provider_outage():
    """A genuine outage → deterministic summary (unchanged) PLUS a
    service_notice so the analysis screen can tell the user, instead
    of silently showing a thinner keyword-extracted summary."""
    result = generate_job_summary_view(
        openai_service=_OutageOpenAI(
            OpenAIUnavailableError("unreachable", category="outage")
        ),
        job_description=_jd(),
    )

    assert result["mode"] == "deterministic"
    assert result["sections"]  # deterministic fallback still works
    assert result["service_notice"]["unavailable"] is True
    assert result["service_notice"]["category"] == "outage"


def test_jd_summary_content_failure_has_no_service_notice():
    result = generate_job_summary_view(
        openai_service=_OutageOpenAI(AgentExecutionError("invalid JSON")),
        job_description=_jd(),
    )

    assert result["mode"] == "deterministic"
    assert "service_notice" not in result
