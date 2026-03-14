import json
import logging
import os
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event_name = getattr(record, "event_name", None)
        if event_name:
            payload["event"] = event_name
        event_data = getattr(record, "event_data", None)
        if event_data:
            payload.update(event_data)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level=None):
    root_logger = logging.getLogger()
    if getattr(root_logger, "_ai_job_logging_configured", False):
        return root_logger

    log_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)
    root_logger._ai_job_logging_configured = True
    return root_logger


def get_logger(name):
    return logging.getLogger(name)


def log_event(logger, level, event_name, message, **event_data):
    logger.log(
        level,
        message,
        extra={
            "event_name": event_name,
            "event_data": event_data,
        },
    )