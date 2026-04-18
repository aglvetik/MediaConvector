from datetime import datetime, timedelta, timezone

import pytest

from app.application.services.user_request_guard_service import UserRequestGuardService


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 4, 18, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value

    def advance(self, *, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


@pytest.mark.asyncio
async def test_user_request_guard_enforces_cooldown() -> None:
    clock = Clock()
    service = UserRequestGuardService(cooldown_seconds=3, now_factory=clock.now)
    first = await service.try_acquire(1)
    assert first.allowed is True
    await service.release(1)

    second = await service.try_acquire(1)
    assert second.allowed is False
    assert second.reason == "cooldown"

    clock.advance(seconds=3)
    third = await service.try_acquire(1)
    assert third.allowed is True


@pytest.mark.asyncio
async def test_user_request_guard_blocks_multiple_active_jobs() -> None:
    clock = Clock()
    service = UserRequestGuardService(cooldown_seconds=3, now_factory=clock.now)
    first = await service.try_acquire(5)
    assert first.allowed is True

    second = await service.try_acquire(5)
    assert second.allowed is False
    assert second.reason == "active_job"
