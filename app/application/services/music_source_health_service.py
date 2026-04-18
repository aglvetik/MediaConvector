from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.entities.music_source_state import MusicSourceState
from app.domain.enums import MusicFailureCode, MusicSourceStatus, is_auth_related_music_failure
from app.domain.interfaces.repositories import MusicSourceStateRepository


@dataclass(slots=True, frozen=True)
class MusicSourceHealthPolicy:
    auth_fail_threshold: int
    degrade_ttl_minutes: int
    healthcheck_enabled: bool


class MusicSourceHealthService:
    def __init__(
        self,
        repository: MusicSourceStateRepository,
        *,
        auth_fail_threshold: int,
        degrade_ttl_minutes: int,
        healthcheck_enabled: bool,
    ) -> None:
        self._repository = repository
        self._policy = MusicSourceHealthPolicy(
            auth_fail_threshold=auth_fail_threshold,
            degrade_ttl_minutes=degrade_ttl_minutes,
            healthcheck_enabled=healthcheck_enabled,
        )

    async def get_state(self, source_name: str, *, configured: bool) -> MusicSourceState:
        existing = await self._repository.get(source_name)
        if existing is not None:
            return existing

        initial_state = MusicSourceState(
            source_name=source_name,
            status=MusicSourceStatus.HEALTHY if configured else MusicSourceStatus.MISSING,
            consecutive_auth_failures=0,
            last_success_at=None,
            last_auth_failure_at=None,
            degraded_until=None,
            last_error_code=None,
            last_error_message=None,
        )
        return await self._repository.save(initial_state)

    async def mark_success(self, source_name: str, *, configured: bool) -> MusicSourceState:
        current = await self.get_state(source_name, configured=configured)
        updated = MusicSourceState(
            source_name=source_name,
            status=MusicSourceStatus.HEALTHY if configured else MusicSourceStatus.MISSING,
            consecutive_auth_failures=0,
            last_success_at=datetime.now(timezone.utc),
            last_auth_failure_at=current.last_auth_failure_at,
            degraded_until=None,
            last_error_code=None,
            last_error_message=None,
        )
        return await self._repository.save(updated)

    async def mark_failure(
        self,
        source_name: str,
        *,
        configured: bool,
        error_code: str,
        error_message: str | None = None,
    ) -> MusicSourceState:
        current = await self.get_state(source_name, configured=configured)
        now = datetime.now(timezone.utc)

        if error_code == MusicFailureCode.COOKIES_MISSING.value:
            consecutive_auth_failures = max(
                current.consecutive_auth_failures + 1,
                self._policy.auth_fail_threshold,
            )
            degraded_until = self._build_degraded_until(now)
            updated = MusicSourceState(
                source_name=source_name,
                status=MusicSourceStatus.MISSING,
                consecutive_auth_failures=consecutive_auth_failures,
                last_success_at=current.last_success_at,
                last_auth_failure_at=now,
                degraded_until=degraded_until,
                last_error_code=error_code,
                last_error_message=error_message,
            )
            return await self._repository.save(updated)

        if is_auth_related_music_failure(error_code):
            consecutive_auth_failures = current.consecutive_auth_failures + 1
            status = (
                MusicSourceStatus.BROKEN
                if consecutive_auth_failures >= self._policy.auth_fail_threshold
                else MusicSourceStatus.SUSPECT
            )
            degraded_until = (
                self._build_degraded_until(now)
                if consecutive_auth_failures >= self._policy.auth_fail_threshold
                else None
            )
            updated = MusicSourceState(
                source_name=source_name,
                status=status,
                consecutive_auth_failures=consecutive_auth_failures,
                last_success_at=current.last_success_at,
                last_auth_failure_at=now,
                degraded_until=degraded_until,
                last_error_code=error_code,
                last_error_message=error_message,
            )
            return await self._repository.save(updated)

        updated = MusicSourceState(
            source_name=source_name,
            status=current.status,
            consecutive_auth_failures=current.consecutive_auth_failures,
            last_success_at=current.last_success_at,
            last_auth_failure_at=current.last_auth_failure_at,
            degraded_until=current.degraded_until,
            last_error_code=error_code,
            last_error_message=error_message,
        )
        return await self._repository.save(updated)

    def _build_degraded_until(self, now: datetime) -> datetime | None:
        if not self._policy.healthcheck_enabled:
            return None
        return now + timedelta(minutes=self._policy.degrade_ttl_minutes)
