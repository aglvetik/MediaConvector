from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.enums.music_source_status import MusicSourceStatus


@dataclass(slots=True, frozen=True)
class MusicSourceState:
    source_name: str
    status: MusicSourceStatus
    consecutive_auth_failures: int
    last_success_at: datetime | None
    last_auth_failure_at: datetime | None
    degraded_until: datetime | None
    last_error_code: str | None = None
    last_error_message: str | None = None

    def is_degraded(self, now: datetime | None = None) -> bool:
        if self.degraded_until is None:
            return False
        current_time = now or datetime.now(timezone.utc)
        return current_time < self.degraded_until
