from __future__ import annotations

import asyncio
from dataclasses import dataclass
from collections.abc import Callable
from datetime import datetime, timedelta, timezone


@dataclass(slots=True, frozen=True)
class UserRequestDecision:
    allowed: bool
    should_notify: bool
    reason: str | None = None


class UserRequestGuardService:
    def __init__(
        self,
        *,
        cooldown_seconds: int,
        feedback_interval_seconds: int | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._cooldown = timedelta(seconds=cooldown_seconds)
        self._feedback_interval = timedelta(seconds=feedback_interval_seconds or cooldown_seconds)
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))
        self._active_users: set[int] = set()
        self._last_started_at: dict[int, datetime] = {}
        self._last_notified_at: dict[int, datetime] = {}
        self._lock = asyncio.Lock()

    async def try_acquire(self, user_id: int) -> UserRequestDecision:
        async with self._lock:
            now = self._now_factory()
            if user_id in self._active_users:
                return UserRequestDecision(allowed=False, should_notify=self._should_notify(user_id, now), reason="active_job")
            last_started_at = self._last_started_at.get(user_id)
            if last_started_at is not None and now - last_started_at < self._cooldown:
                return UserRequestDecision(allowed=False, should_notify=self._should_notify(user_id, now), reason="cooldown")
            self._active_users.add(user_id)
            self._last_started_at[user_id] = now
            return UserRequestDecision(allowed=True, should_notify=False, reason=None)

    async def release(self, user_id: int) -> None:
        async with self._lock:
            self._active_users.discard(user_id)

    def _should_notify(self, user_id: int, now: datetime) -> bool:
        last_notified_at = self._last_notified_at.get(user_id)
        if last_notified_at is not None and now - last_notified_at < self._feedback_interval:
            return False
        self._last_notified_at[user_id] = now
        return True
