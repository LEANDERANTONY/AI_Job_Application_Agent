import json
import logging

from src.logging_utils import JsonFormatter, configure_logging, log_event


def test_json_formatter_includes_event_and_metadata():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="src.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Structured log message.",
        args=(),
        exc_info=None,
    )
    record.event_name = "test_event"
    record.event_data = {"mode": "openai", "duration_ms": 12.5}

    payload = json.loads(formatter.format(record))

    assert payload["event"] == "test_event"
    assert payload["message"] == "Structured log message."
    assert payload["mode"] == "openai"
    assert payload["duration_ms"] == 12.5


def test_configure_logging_is_idempotent():
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_marker = getattr(root_logger, "_ai_job_logging_configured", False)
    try:
        if hasattr(root_logger, "_ai_job_logging_configured"):
            delattr(root_logger, "_ai_job_logging_configured")
        configured_once = configure_logging(level="INFO")
        configured_twice = configure_logging(level="DEBUG")

        assert configured_once is configured_twice
        assert getattr(configured_once, "_ai_job_logging_configured", False) is True
        assert len(configured_once.handlers) == 1
    finally:
        root_logger.handlers.clear()
        for handler in original_handlers:
            root_logger.addHandler(handler)
        if original_marker:
            root_logger._ai_job_logging_configured = original_marker
        elif hasattr(root_logger, "_ai_job_logging_configured"):
            delattr(root_logger, "_ai_job_logging_configured")


def test_log_event_attaches_structured_metadata(caplog):
    logger = logging.getLogger("src.test_logging")

    with caplog.at_level(logging.INFO, logger="src.test_logging"):
        log_event(logger, logging.INFO, "workflow_started", "Workflow started.", mode="openai")

    record = caplog.records[-1]
    assert record.event_name == "workflow_started"
    assert record.event_data == {"mode": "openai"}