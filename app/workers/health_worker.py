from __future__ import annotations

import asyncio

from app.application.services.health_service import HealthService
from app.infrastructure.logging import get_logger, log_event


class HealthWorker:
    def __init__(self, *, interval_minutes: int, health_service: HealthService) -> None:
        self._interval_seconds = interval_minutes * 60
        self._health_service = health_service
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._logger = get_logger(__name__)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                try:
                    report = await self._health_service.collect()
                    log_event(
                        self._logger,
                        20,
                        "health_report",
                        database_ok=report.database_ok,
                        temp_dir_ok=report.temp_dir_ok,
                        ffmpeg_ok=report.ffmpeg_ok,
                        ytdlp_ok=report.ytdlp_ok,
                        gallerydl_ok=report.gallerydl_ok,
                        bot_ready=report.bot_ready,
                        stuck_jobs=report.stuck_jobs,
                        temp_dir_size_bytes=report.temp_dir_size_bytes,
                    )
                except Exception as exc:
                    log_event(self._logger, 40, "health_worker_failed", error=str(exc))
