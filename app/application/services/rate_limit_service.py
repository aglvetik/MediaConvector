from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Deque

from app.domain.errors import RateLimitExceededError


class RateLimitService:
    def __init__(self, *, enabled: bool, requests_per_minute: int) -> None:
        self._enabled = enabled
        self._requests_per_minute = requests_per_minute
        self._window = timedelta(minutes=1)
        self._events: dict[int, Deque[datetime]] = defaultdict(deque)

    def ensure_allowed(self, user_id: int) -> None:
        if not self._enabled:
            return
        now = datetime.now(timezone.utc)
        bucket = self._events[user_id]
        cutoff = now - self._window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self._requests_per_minute:
            raise RateLimitExceededError()
        bucket.append(now)
