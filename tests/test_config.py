from src.config import resolve_job_backend_base_url


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
