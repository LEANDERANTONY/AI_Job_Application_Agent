from src.config import (
    get_openai_max_completion_tokens_for_task,
    resolve_job_backend_base_url,
)


def test_product_help_budget_matches_its_assistant_siblings():
    """Regression: product_help routes to a gpt-5-class reasoning
    model, so max_output_tokens caps reasoning + output combined. The
    old 700 truncated thorough help answers into the canned fallback.
    It must stay at parity with the assistant / application_qa
    siblings so a future re-tighten fails here."""
    product_help = get_openai_max_completion_tokens_for_task(
        "assistant_product_help"
    )
    assistant = get_openai_max_completion_tokens_for_task("assistant")
    application_qa = get_openai_max_completion_tokens_for_task(
        "assistant_application_qa"
    )

    assert product_help >= 1400
    assert product_help == assistant == application_qa


def test_resolve_job_backend_base_url_prefers_explicit_base_url():
    resolved = resolve_job_backend_base_url(
        explicit_base_url="https://jobs-backend.example.com/",
        hostport="internal-service:10000",
    )

    assert resolved == "https://jobs-backend.example.com"


def test_resolve_job_backend_base_url_builds_private_network_url_from_hostport():
    resolved = resolve_job_backend_base_url(
        explicit_base_url="",
        hostport="ai-job-application-agent-backend:10000",
    )

    assert resolved == "http://ai-job-application-agent-backend:10000"


def test_resolve_job_backend_base_url_falls_back_to_local_default():
    resolved = resolve_job_backend_base_url("", "")

    assert resolved == "http://localhost:8000"
