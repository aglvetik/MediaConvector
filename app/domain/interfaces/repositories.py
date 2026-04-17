from __future__ import annotations

from typing import Protocol

from app.domain.entities.cache_entry import CacheEntry
from app.domain.entities.download_job import DownloadJob
from app.domain.enums.cache_status import CacheStatus
from app.domain.enums.job_status import JobStatus


class CacheRepository(Protocol):
    async def get_by_normalized_key(self, normalized_key: str) -> CacheEntry | None:
        ...

    async def upsert_processing(self, entry: CacheEntry) -> CacheEntry:
        ...

    async def save_result(self, entry: CacheEntry) -> CacheEntry:
        ...

    async def mark_invalid(self, normalized_key: str) -> None:
        ...

    async def increment_hit(self, normalized_key: str) -> None:
        ...

    async def count_by_status(self) -> dict[CacheStatus, int]:
        ...


class DownloadJobRepository(Protocol):
    async def create(self, job: DownloadJob) -> DownloadJob:
        ...

    async def update_status(
        self,
        request_id: str,
        status: JobStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        ...

    async def count_stuck_jobs(self, stale_after_minutes: int) -> int:
        ...

    async def mark_stale_jobs_failed(self, stale_after_minutes: int) -> int:
        ...


class ProcessedMessageRepository(Protocol):
    async def claim(self, chat_id: int, message_id: int, normalized_key: str) -> bool:
        ...

    async def mark_finished(self, chat_id: int, message_id: int, normalized_key: str, *, success: bool) -> None:
        ...


class RequestLogRepository(Protocol):
    async def log_started(
        self,
        request_id: str,
        chat_id: int,
        user_id: int,
        message_id: int,
        normalized_key: str,
        original_url: str,
    ) -> None:
        ...

    async def log_finished(
        self,
        request_id: str,
        *,
        success: bool,
        delivery_status: str,
        cache_hit: bool,
        error_code: str | None = None,
    ) -> None:
        ...

    async def count_recent(self) -> int:
        ...
