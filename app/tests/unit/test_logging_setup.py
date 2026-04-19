from __future__ import annotations

import json
import logging

from app.infrastructure.logging.setup import JsonFormatter, log_event


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.messages: list[str] = []
        self.setFormatter(JsonFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        self.messages.append(self.format(record))


def test_log_event_sanitizes_reserved_log_record_fields() -> None:
    logger = logging.getLogger("tests.logging.sanitized")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = _RecordingHandler()
    logger.addHandler(handler)

    log_event(
        logger,
        logging.INFO,
        "audio_metadata_prepared",
        filename="track.mp3",
        module="delivery_service",
        pathname="/tmp/track.mp3",
        message="shadowed",
        taskName="worker-1",
    )

    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.__dict__["extra_filename"] == "track.mp3"
    assert record.__dict__["extra_module"] == "delivery_service"
    assert record.__dict__["extra_pathname"] == "/tmp/track.mp3"
    assert record.__dict__["extra_message"] == "shadowed"
    assert record.__dict__["extra_taskName"] == "worker-1"

    payload = json.loads(handler.messages[0])
    assert payload["event_name"] == "audio_metadata_prepared"
    assert payload["extra_filename"] == "track.mp3"
    assert payload["extra_module"] == "delivery_service"
    assert payload["extra_pathname"] == "/tmp/track.mp3"
    assert payload["extra_message"] == "shadowed"
    assert payload["extra_taskName"] == "worker-1"


def test_log_event_never_raises_when_logger_fails() -> None:
    class _BrokenLogger(logging.Logger):
        def log(self, level, msg, *args, **kwargs):  # type: ignore[override]
            raise RuntimeError("boom")

    logger = _BrokenLogger("tests.logging.broken")

    log_event(logger, logging.INFO, "safe_logging", filename="still-safe.mp3")
