from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.enums.music_source_status import MusicSourceStatus


def ensure_utc_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "last_success_at", ensure_utc_aware(self.last_success_at))
        object.__setattr__(self, "last_auth_failure_at", ensure_utc_aware(self.last_auth_failure_at))
        object.__setattr__(self, "degraded_until", ensure_utc_aware(self.degraded_until))

    def is_degraded(self, now: datetime | None = None) -> bool:
        degraded_until = ensure_utc_aware(self.degraded_until)
        if degraded_until is None:
            return False
        current_time = ensure_utc_aware(now or datetime.now(timezone.utc))
        if current_time is None:
            return False
        return current_time < degraded_until
