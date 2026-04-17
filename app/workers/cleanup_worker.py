from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.infrastructure.logging import get_logger, log_event


class CleanupWorker:
    def __init__(
        self,
        *,
        interval_minutes: int,
        cleanup_callback: Callable[[], Awaitable[int]],
        stale_jobs_callback: Callable[[], Awaitable[int]],
    ) -> None:
        self._interval_seconds = interval_minutes * 60
        self._cleanup_callback = cleanup_callback
        self._stale_jobs_callback = stale_jobs_callback
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

    async def run_once(self) -> tuple[int, int]:
        removed = await self._cleanup_callback()
        stale_jobs = await self._stale_jobs_callback()
        log_event(self._logger, 20, "temp_cleanup_completed", removed_entries=removed, stale_jobs_marked=stale_jobs)
        return removed, stale_jobs

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                try:
                    await self.run_once()
                except Exception as exc:
                    log_event(self._logger, 40, "cleanup_worker_failed", error=str(exc))
