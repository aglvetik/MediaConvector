from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.infrastructure.logging import get_logger, log_event

T = TypeVar("T")


class InFlightDedupService:
    def __init__(self) -> None:
        self._logger = get_logger(__name__)
        self._inflight: dict[str, asyncio.Task[T]] = {}
        self._lock = asyncio.Lock()

    async def run_or_join(self, key: str, factory: Callable[[], Awaitable[T]]) -> tuple[T, bool]:
        async with self._lock:
            existing = self._inflight.get(key)
            if existing is None:
                task = asyncio.create_task(factory())
                self._inflight[key] = task
                joined = False
            else:
                task = existing
                joined = True
                log_event(self._logger, 20, "in_flight_joined", normalized_key=key)

        try:
            return await task, joined
        finally:
            if not joined:
                async with self._lock:
                    current = self._inflight.get(key)
                    if current is task:
                        self._inflight.pop(key, None)

