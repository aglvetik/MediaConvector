from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.enums.job_status import JobStatus


@dataclass(slots=True)
class DownloadJob:
    id: int | None
    request_id: str
    normalized_key: str
    status: JobStatus
    chat_id: int
    user_id: int
    original_url: str
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None

