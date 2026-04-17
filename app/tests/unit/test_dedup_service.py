import asyncio

from app.application.services.dedup_service import InFlightDedupService


async def test_dedup_service_runs_factory_only_once() -> None:
    service = InFlightDedupService()
    counter = 0

    async def factory() -> int:
        nonlocal counter
        counter += 1
        await asyncio.sleep(0.01)
        return 42

    result1, joined1 = await asyncio.gather(
        service.run_or_join("key", factory),
        service.run_or_join("key", factory),
    )
    assert result1[0] == 42
    assert joined1[0] == 42
    assert counter == 1
    assert any(joined for _, joined in (result1, joined1))

