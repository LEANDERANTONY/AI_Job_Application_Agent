import json
import logging

from src.logging_utils import JsonFormatter


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