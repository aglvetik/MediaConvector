from __future__ import annotations

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
