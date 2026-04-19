from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

from sqlalchemy import text

from app.domain.interfaces.repositories import CacheRepository, DownloadJobRepository, RequestLogRepository
from app.domain.interfaces.telegram_gateway import TelegramGateway
from app.infrastructure.persistence.sqlite.session import Database
from app.infrastructure.temp import TempFileManager

T = TypeVar("T")


@dataclass(slots=True, frozen=True)
class HealthReport:
    database_ok: bool
    temp_dir_ok: bool
    ffmpeg_ok: bool
    ytdlp_ok: bool
    gallerydl_ok: bool
    bot_ready: bool
    stuck_jobs: int
    temp_dir_size_bytes: int
    cache_status_counts: dict[str, int]
    total_requests: int


class HealthService:
    def __init__(
        self,
        *,
        database: Database,
        cache_repository: CacheRepository,
        job_repository: DownloadJobRepository,
        request_log_repository: RequestLogRepository,
        temp_file_manager: TempFileManager,
        telegram_gateway: TelegramGateway,
        ffmpeg_path: str,
        ytdlp_path: str,
        gallerydl_path: str,
        job_stale_after_minutes: int,
    ) -> None:
        self._database = database
        self._cache_repository = cache_repository
        self._job_repository = job_repository
        self._request_log_repository = request_log_repository
        self._temp_file_manager = temp_file_manager
        self._telegram_gateway = telegram_gateway
        self._ffmpeg_path = ffmpeg_path
        self._ytdlp_path = ytdlp_path
        self._gallerydl_path = gallerydl_path
        self._job_stale_after_minutes = job_stale_after_minutes

    async def collect(self) -> HealthReport:
        database_ok = True
        try:
            async with self._database.session() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            database_ok = False
        temp_dir_ok = self._temp_file_manager.root.exists() and self._temp_file_manager.root.is_dir()
        ffmpeg_ok = self._binary_available(self._ffmpeg_path)
        ytdlp_ok = self._binary_available(self._ytdlp_path)
        gallerydl_ok = self._binary_available(self._gallerydl_path)
        stuck_jobs = await self._safe_call(lambda: self._job_repository.count_stuck_jobs(self._job_stale_after_minutes), 0)
        temp_dir_size_bytes = await self._temp_file_manager.directory_size_bytes()
        cache_stats = await self._safe_call(self._cache_repository.count_by_status, {})
        total_requests = await self._safe_call(self._request_log_repository.count_recent, 0)
        return HealthReport(
            database_ok=database_ok,
            temp_dir_ok=temp_dir_ok,
            ffmpeg_ok=ffmpeg_ok,
            ytdlp_ok=ytdlp_ok,
            gallerydl_ok=gallerydl_ok,
            bot_ready=self._telegram_gateway.is_ready,
            stuck_jobs=stuck_jobs,
            temp_dir_size_bytes=temp_dir_size_bytes,
            cache_status_counts={status.value: count for status, count in cache_stats.items()},
            total_requests=total_requests,
        )

    async def ping_text(self) -> str:
        report = await self.collect()
        overall = all((report.database_ok, report.temp_dir_ok, report.ffmpeg_ok, report.ytdlp_ok, report.gallerydl_ok, report.bot_ready))
        return (
            f"pong | ok={str(overall).lower()} | db={report.database_ok} | temp={report.temp_dir_ok} "
            f"| ffmpeg={report.ffmpeg_ok} | yt-dlp={report.ytdlp_ok} | gallery-dl={report.gallerydl_ok} "
            f"| bot={report.bot_ready} | stuck_jobs={report.stuck_jobs}"
        )

    @staticmethod
    def _binary_available(binary: str) -> bool:
        return Path(binary).exists() or shutil.which(binary) is not None

    async def _safe_call(self, operation: Callable[[], Awaitable[T]], fallback: T) -> T:
        try:
            return await operation()
        except Exception:
            return fallback
