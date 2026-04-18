from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio

from app.application.services import (
    CacheService,
    DeliveryService,
    InFlightDedupService,
    MediaPipelineService,
    MetricsService,
    MusicPipelineService,
    MusicSearchService,
    ProcessMessageService,
    RateLimitService,
    UserRequestGuardService,
)
from app.infrastructure.persistence.sqlite import (
    Database,
    SqlAlchemyCacheRepository,
    SqlAlchemyDownloadJobRepository,
    SqlAlchemyProcessedMessageRepository,
    SqlAlchemyRequestLogRepository,
)
from app.infrastructure.persistence.sqlite.base import Base
from app.infrastructure.temp import TempFileManager
from app.tests.fakes import FakeAudioDownloadClient, FakeFfmpegAdapter, FakeGateway, FakeMusicProvider, FakeProvider


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> Database:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield database
    finally:
        await database.dispose()


@dataclass(slots=True)
class ServiceHarness:
    cache_service: CacheService
    delivery_service: DeliveryService
    metrics_service: MetricsService
    process_message_service: ProcessMessageService
    gateway: FakeGateway
    provider: FakeProvider
    music_provider: FakeMusicProvider
    audio_downloader: FakeAudioDownloadClient
    ffmpeg: FakeFfmpegAdapter
    temp_manager: TempFileManager
    cache_repository: SqlAlchemyCacheRepository
    request_log_repository: SqlAlchemyRequestLogRepository
    job_repository: SqlAlchemyDownloadJobRepository


@pytest_asyncio.fixture
async def service_harness(database: Database, tmp_path: Path) -> ServiceHarness:
    cache_repository = SqlAlchemyCacheRepository(database)
    request_log_repository = SqlAlchemyRequestLogRepository(database)
    job_repository = SqlAlchemyDownloadJobRepository(database)
    processed_message_repository = SqlAlchemyProcessedMessageRepository(database)
    gateway = FakeGateway()
    provider = FakeProvider()
    music_provider = FakeMusicProvider()
    audio_downloader = FakeAudioDownloadClient()
    ffmpeg = FakeFfmpegAdapter()
    metrics = MetricsService()
    cache_service = CacheService(cache_repository)
    delivery_service = DeliveryService(gateway)
    temp_manager = TempFileManager(tmp_path / "tmp", ttl_minutes=30)
    dedup_service = InFlightDedupService()
    media_pipeline_service = MediaPipelineService(
        cache_service=cache_service,
        dedup_service=dedup_service,
        delivery_service=delivery_service,
        job_repository=job_repository,
        ffmpeg_adapter=ffmpeg,
        temp_file_manager=temp_manager,
        metrics_service=metrics,
    )
    music_search_service = MusicSearchService(provider=music_provider, max_query_length=120)
    music_pipeline_service = MusicPipelineService(
        cache_service=cache_service,
        dedup_service=dedup_service,
        delivery_service=delivery_service,
        job_repository=job_repository,
        temp_file_manager=temp_manager,
        audio_download_client=audio_downloader,
        ffmpeg_adapter=ffmpeg,
        music_search_service=music_search_service,
        metrics_service=metrics,
    )
    process_message_service = ProcessMessageService(
        providers=(provider,),
        delivery_service=delivery_service,
        media_pipeline_service=media_pipeline_service,
        music_search_service=music_search_service,
        music_pipeline_service=music_pipeline_service,
        rate_limit_service=RateLimitService(enabled=True, requests_per_minute=10),
        user_request_guard_service=UserRequestGuardService(cooldown_seconds=3),
        processed_message_repository=processed_message_repository,
        request_log_repository=request_log_repository,
        metrics_service=metrics,
    )
    return ServiceHarness(
        cache_service=cache_service,
        delivery_service=delivery_service,
        metrics_service=metrics,
        process_message_service=process_message_service,
        gateway=gateway,
        provider=provider,
        music_provider=music_provider,
        audio_downloader=audio_downloader,
        ffmpeg=ffmpeg,
        temp_manager=temp_manager,
        cache_repository=cache_repository,
        request_log_repository=request_log_repository,
        job_repository=job_repository,
    )
