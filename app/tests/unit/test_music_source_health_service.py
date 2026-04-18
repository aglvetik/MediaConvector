from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.application.services.music_source_health_service import MusicSourceHealthService
from app.domain.entities.music_source_state import MusicSourceState
from app.domain.enums import MusicFailureCode, MusicSourceStatus


class InMemoryMusicSourceStateRepository:
    def __init__(self) -> None:
        self._states: dict[str, MusicSourceState] = {}

    async def get(self, source_name: str) -> MusicSourceState | None:
        return self._states.get(source_name)

    async def save(self, state: MusicSourceState) -> MusicSourceState:
        self._states[state.source_name] = state
        return state


async def test_repeated_login_required_marks_source_degraded() -> None:
    service = MusicSourceHealthService(
        InMemoryMusicSourceStateRepository(),
        auth_fail_threshold=2,
        degrade_ttl_minutes=30,
        healthcheck_enabled=True,
    )

    first = await service.mark_failure(
        "youtube_cookies",
        configured=True,
        error_code=MusicFailureCode.LOGIN_REQUIRED.value,
        error_message="login required",
    )
    second = await service.mark_failure(
        "youtube_cookies",
        configured=True,
        error_code=MusicFailureCode.LOGIN_REQUIRED.value,
        error_message="login required",
    )

    assert first.status == MusicSourceStatus.SUSPECT
    assert first.degraded_until is None
    assert second.status == MusicSourceStatus.BROKEN
    assert second.degraded_until is not None
    assert second.is_degraded() is True


async def test_success_recovers_source_health_after_degraded_mode() -> None:
    service = MusicSourceHealthService(
        InMemoryMusicSourceStateRepository(),
        auth_fail_threshold=2,
        degrade_ttl_minutes=30,
        healthcheck_enabled=True,
    )

    await service.mark_failure(
        "youtube_cookies",
        configured=True,
        error_code=MusicFailureCode.LOGIN_REQUIRED.value,
    )
    await service.mark_failure(
        "youtube_cookies",
        configured=True,
        error_code=MusicFailureCode.LOGIN_REQUIRED.value,
    )
    recovered = await service.mark_success("youtube_cookies", configured=True)

    assert recovered.status == MusicSourceStatus.HEALTHY
    assert recovered.consecutive_auth_failures == 0
    assert recovered.degraded_until is None
    assert recovered.last_success_at is not None


def test_is_degraded_true_for_future_datetime() -> None:
    state = MusicSourceState(
        source_name="youtube_cookies",
        status=MusicSourceStatus.BROKEN,
        consecutive_auth_failures=2,
        last_success_at=None,
        last_auth_failure_at=datetime.now(timezone.utc),
        degraded_until=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    assert state.is_degraded() is True


def test_is_degraded_false_for_past_datetime() -> None:
    state = MusicSourceState(
        source_name="youtube_cookies",
        status=MusicSourceStatus.BROKEN,
        consecutive_auth_failures=2,
        last_success_at=None,
        last_auth_failure_at=datetime.now(timezone.utc),
        degraded_until=datetime.now(timezone.utc) - timedelta(minutes=5),
    )

    assert state.is_degraded() is False


def test_is_degraded_handles_naive_degraded_until_without_type_error() -> None:
    naive_future = datetime.utcnow() + timedelta(minutes=5)
    state = MusicSourceState(
        source_name="youtube_cookies",
        status=MusicSourceStatus.BROKEN,
        consecutive_auth_failures=2,
        last_success_at=None,
        last_auth_failure_at=datetime.utcnow(),
        degraded_until=naive_future,
    )

    assert state.is_degraded(now=datetime.now(timezone.utc)) is True
