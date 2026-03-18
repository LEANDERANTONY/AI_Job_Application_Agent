from src.ui.legal import get_privacy_policy_markdown, get_privacy_policy_url


def test_privacy_policy_mentions_actual_service_providers_and_scope():
    policy = get_privacy_policy_markdown()

    assert "Supabase" in policy
    assert "OpenAI" in policy
    assert "Render" in policy
    assert "does not request Gmail mailbox access" in policy
    assert "saved workspace for an authenticated user is retained for 24 hours by default" in policy


def test_privacy_policy_url_uses_base_url_when_available():
    assert (
        get_privacy_policy_url("https://ai-job-application-agent.onrender.com")
        == "https://ai-job-application-agent.onrender.com/?view=privacy"
    )