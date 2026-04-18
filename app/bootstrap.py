from __future__ import annotations

import asyncio
from dataclasses import dataclass

from aiogram import Bot

from app.application.services import (
    CacheService,
    DeliveryService,
    HealthService,
    InFlightDedupService,
    MediaPipelineService,
    MetricsService,
    MusicPipelineService,
    MusicSearchService,
    ProcessMessageService,
    RateLimitService,
    UserRequestGuardService,
)
from app.config import Settings
from app.infrastructure.downloaders import AudioDownloadClient, YtDlpClient
from app.infrastructure.media import FfmpegAdapter
from app.infrastructure.persistence.sqlite import (
    Database,
    SqlAlchemyCacheRepository,
    SqlAlchemyDownloadJobRepository,
    SqlAlchemyProcessedMessageRepository,
    SqlAlchemyRequestLogRepository,
)
from app.infrastructure.providers import TikTokProvider, YouTubeMusicProvider
from app.infrastructure.telegram import AiogramTelegramGateway
from app.infrastructure.temp import TempFileManager
from app.workers import CleanupWorker, HealthWorker


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    bot: Bot
    database: Database
    gateway: AiogramTelegramGateway
    cache_service: CacheService
    delivery_service: DeliveryService
    health_service: HealthService
    metrics_service: MetricsService
    process_message_service: ProcessMessageService
    cleanup_worker: CleanupWorker
    health_worker: HealthWorker


def build_container(settings: Settings) -> AppContainer:
    database = Database(settings.database_url)
    bot = Bot(token=settings.bot_token)
    gateway = AiogramTelegramGateway(bot=bot, max_file_size_bytes=settings.max_file_size_bytes)

    cache_repository = SqlAlchemyCacheRepository(database)
    download_job_repository = SqlAlchemyDownloadJobRepository(database)
    processed_message_repository = SqlAlchemyProcessedMessageRepository(database)
    request_log_repository = SqlAlchemyRequestLogRepository(database)

    temp_file_manager = TempFileManager(settings.temp_dir, settings.temp_file_ttl_minutes)
    download_semaphore = asyncio.Semaphore(settings.max_parallel_downloads)
    ffmpeg_semaphore = asyncio.Semaphore(settings.max_parallel_ffmpeg)
    ytdlp_client = YtDlpClient(
        binary_path=settings.ytdlp_path,
        timeout_seconds=settings.download_timeout_seconds,
        semaphore=download_semaphore,
    )
    ffmpeg_adapter = FfmpegAdapter(
        ffmpeg_path=settings.ffmpeg_path,
        timeout_seconds=settings.request_timeout_seconds,
        semaphore=ffmpeg_semaphore,
    )
    tiktok_provider = TikTokProvider(
        downloader=ytdlp_client,
        request_timeout_seconds=settings.request_timeout_seconds,
    )
    youtube_music_provider = YouTubeMusicProvider(
        timeout_seconds=settings.music_search_timeout_seconds,
        semaphore=download_semaphore,
    )
    audio_download_client = AudioDownloadClient(
        timeout_seconds=settings.download_timeout_seconds,
        semaphore=download_semaphore,
    )

    metrics_service = MetricsService()
    cache_service = CacheService(cache_repository)
    delivery_service = DeliveryService(gateway)
    dedup_service = InFlightDedupService()
    music_search_service = MusicSearchService(
        provider=youtube_music_provider,
        max_query_length=settings.max_music_query_length,
    )
    media_pipeline_service = MediaPipelineService(
        cache_service=cache_service,
        dedup_service=dedup_service,
        delivery_service=delivery_service,
        job_repository=download_job_repository,
        ffmpeg_adapter=ffmpeg_adapter,
        temp_file_manager=temp_file_manager,
        metrics_service=metrics_service,
    )
    music_pipeline_service = MusicPipelineService(
        cache_service=cache_service,
        dedup_service=dedup_service,
        delivery_service=delivery_service,
        job_repository=download_job_repository,
        temp_file_manager=temp_file_manager,
        audio_download_client=audio_download_client,
        ffmpeg_adapter=ffmpeg_adapter,
        music_search_service=music_search_service,
        metrics_service=metrics_service,
    )
    rate_limit_service = RateLimitService(
        enabled=settings.rate_limit_enabled,
        requests_per_minute=settings.user_requests_per_minute,
    )
    user_request_guard_service = UserRequestGuardService(
        cooldown_seconds=settings.user_request_cooldown_seconds,
    )
    process_message_service = ProcessMessageService(
        providers=(tiktok_provider,),
        delivery_service=delivery_service,
        media_pipeline_service=media_pipeline_service,
        music_search_service=music_search_service,
        music_pipeline_service=music_pipeline_service,
        rate_limit_service=rate_limit_service,
        user_request_guard_service=user_request_guard_service,
        processed_message_repository=processed_message_repository,
        request_log_repository=request_log_repository,
        metrics_service=metrics_service,
    )
    health_service = HealthService(
        database=database,
        cache_repository=cache_repository,
        job_repository=download_job_repository,
        request_log_repository=request_log_repository,
        temp_file_manager=temp_file_manager,
        telegram_gateway=gateway,
        ffmpeg_path=settings.ffmpeg_path,
        ytdlp_path=settings.ytdlp_path,
        job_stale_after_minutes=settings.job_stale_after_minutes,
    )
    cleanup_worker = CleanupWorker(
        interval_minutes=settings.cleanup_interval_minutes,
        cleanup_callback=temp_file_manager.cleanup_expired,
        stale_jobs_callback=lambda: download_job_repository.mark_stale_jobs_failed(settings.job_stale_after_minutes),
    )
    health_worker = HealthWorker(interval_minutes=settings.health_interval_minutes, health_service=health_service)

    return AppContainer(
        settings=settings,
        bot=bot,
        database=database,
        gateway=gateway,
        cache_service=cache_service,
        delivery_service=delivery_service,
        health_service=health_service,
        metrics_service=metrics_service,
        process_message_service=process_message_service,
        cleanup_worker=cleanup_worker,
        health_worker=health_worker,
    )
