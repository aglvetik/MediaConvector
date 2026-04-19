from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from app.application.services.health_service import HealthService
from app.infrastructure.temp import TempFileManager


class BrokenDatabase:
    @asynccontextmanager
    async def session(self):
        raise RuntimeError("db down")
        yield


class BrokenCacheRepository:
    async def count_by_status(self):
        raise RuntimeError("cache repo down")


class BrokenJobRepository:
    async def count_stuck_jobs(self, stale_after_minutes: int):
        raise RuntimeError("job repo down")


class BrokenRequestLogRepository:
    async def count_recent(self):
        raise RuntimeError("request log down")


class ReadyGateway:
    @property
    def is_ready(self) -> bool:
        return True


async def test_health_service_collect_handles_backend_failures(tmp_path: Path) -> None:
    manager = TempFileManager(tmp_path / "tmp", ttl_minutes=1)
    service = HealthService(
        database=BrokenDatabase(),
        cache_repository=BrokenCacheRepository(),
        job_repository=BrokenJobRepository(),
        request_log_repository=BrokenRequestLogRepository(),
        temp_file_manager=manager,
        telegram_gateway=ReadyGateway(),
        ffmpeg_path="ffmpeg",
        ytdlp_path="yt-dlp",
        gallerydl_path="gallery-dl",
        job_stale_after_minutes=15,
    )

    report = await service.collect()

    assert report.database_ok is False
    assert isinstance(report.gallerydl_ok, bool)
    assert report.stuck_jobs == 0
    assert report.cache_status_counts == {}
    assert report.total_requests == 0
