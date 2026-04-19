from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

_RESERVED_LOG_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "taskName",
    "thread",
    "threadName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "event_name"):
            payload["event_name"] = getattr(record, "event_name")
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in _RESERVED_LOG_RECORD_FIELDS:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, level: int, event_name: str, **fields: object) -> None:
    extra_fields = {"event_name": event_name, **_sanitize_extra_fields(fields)}
    try:
        logger.log(level, event_name, extra=extra_fields)
    except Exception:
        try:
            logging.Logger._log(logger, level, event_name, (), extra={"event_name": event_name})
        except Exception:
            pass


def _sanitize_extra_fields(fields: dict[str, object]) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    for key, value in fields.items():
        safe_key = key
        if safe_key in _RESERVED_LOG_RECORD_FIELDS or safe_key == "event_name":
            safe_key = f"extra_{safe_key}"
        while safe_key in _RESERVED_LOG_RECORD_FIELDS or safe_key == "event_name" or safe_key in sanitized:
            safe_key = f"extra_{safe_key}"
        sanitized[safe_key] = value
    return sanitized
