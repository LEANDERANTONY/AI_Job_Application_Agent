from src.errors import AgentExecutionError, OpenAIUnavailableError
from src.llm_outage import message_for_category, outage_notice


def test_outage_notice_only_fires_for_a_genuine_provider_outage():
    # A genuine provider outage → a serialisable, cause-accurate notice.
    notice = outage_notice(
        OpenAIUnavailableError("unreachable", category="outage")
    )
    assert notice == {
        "unavailable": True,
        "category": "outage",
        "message": message_for_category("outage"),
    }

    rl = outage_notice(OpenAIUnavailableError("429", category="rate_limited"))
    assert rl["category"] == "rate_limited"
    assert "rate-limit" in rl["message"].lower()

    mis = outage_notice(
        OpenAIUnavailableError("bad key", category="misconfigured")
    )
    # Misconfig copy stays generic — we don't publicly blame OpenAI for
    # our own key/model bug.
    assert "openai" not in mis["message"].lower()

    # A plain content failure (or anything that isn't an
    # OpenAIUnavailableError) → None: it degrades silently as before,
    # there's nothing for the user to wait out.
    assert outage_notice(AgentExecutionError("invalid JSON")) is None
    assert outage_notice(RuntimeError("boom")) is None


def test_message_for_category_defaults_to_outage_copy():
    assert message_for_category(None) == message_for_category("outage")
    assert message_for_category("nonsense") == message_for_category("outage")
    assert "OpenAI" in message_for_category("outage")
