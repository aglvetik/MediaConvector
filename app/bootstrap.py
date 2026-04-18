from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

from aiogram import Bot

from app.application.services import (
    CacheService,
    DeliveryService,
    HealthService,
    InFlightDedupService,
    MediaPipelineService,
    MetricsService,
    MusicProviderDownloadStrategy,
    MusicProviderResolverStrategy,
    MusicAcquisitionService,
    MusicPipelineService,
    MusicSearchService,
    MusicSourceHealthService,
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
    SqlAlchemyMusicSourceStateRepository,
    SqlAlchemyProcessedMessageRepository,
    SqlAlchemyRequestLogRepository,
)
from app.infrastructure.providers import (
    HttpMusicMetadataProvider,
    RemoteMusicDownloadProvider,
    StaticCookieFileProvider,
    TikTokProvider,
    YouTubeMusicProvider,
)
from app.infrastructure.telegram import AiogramTelegramGateway
from app.infrastructure.temp import TempFileManager
from app.infrastructure.logging import get_logger, log_event
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
    logger = get_logger(__name__)
    database = Database(settings.database_url)
    bot = Bot(token=settings.bot_token)
    gateway = AiogramTelegramGateway(bot=bot, max_file_size_bytes=settings.max_file_size_bytes)
    cookies_file = settings.resolved_ytdlp_cookies_file

    logger.info("cookies_path", extra={"path": str(cookies_file) if cookies_file is not None else None})
    logger.info(
        "startup_paths",
        extra={
            "cookies": str(cookies_file) if cookies_file is not None else None,
            "cookies_exists": bool(cookies_file and os.path.exists(cookies_file)),
            "ffmpeg": settings.ffmpeg_path,
            "ytdlp": settings.ytdlp_path,
            "music_remote_provider_configured": bool(settings.music_remote_provider_url),
            "music_resolver_order": settings.music_resolver_order_list,
            "music_download_provider_order": settings.music_download_provider_order_list,
        },
    )
    log_event(
        logger,
        logging.INFO,
        "startup_paths",
        cookies=str(cookies_file) if cookies_file is not None else None,
        cookies_exists=bool(cookies_file and os.path.exists(cookies_file)),
        ffmpeg=settings.ffmpeg_path,
        ytdlp=settings.ytdlp_path,
        music_remote_provider_configured=bool(settings.music_remote_provider_url),
        music_resolver_order=settings.music_resolver_order_list,
        music_download_provider_order=settings.music_download_provider_order_list,
    )

    cache_repository = SqlAlchemyCacheRepository(database)
    download_job_repository = SqlAlchemyDownloadJobRepository(database)
    music_source_state_repository = SqlAlchemyMusicSourceStateRepository(database)
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
    music_metadata_provider = HttpMusicMetadataProvider(timeout_seconds=settings.request_timeout_seconds)
    remote_music_download_provider = RemoteMusicDownloadProvider(
        endpoint_url=settings.music_remote_provider_url,
        access_token=settings.music_remote_provider_token,
        timeout_seconds=settings.music_remote_provider_timeout_seconds,
        semaphore=download_semaphore,
    )
    audio_download_client = AudioDownloadClient(
        timeout_seconds=settings.download_timeout_seconds,
        semaphore=download_semaphore,
        audio_only=settings.music_audio_only,
    )

    metrics_service = MetricsService()
    cache_service = CacheService(cache_repository)
    delivery_service = DeliveryService(gateway)
    dedup_service = InFlightDedupService()
    music_search_service = MusicSearchService(
        max_query_length=settings.max_music_query_length,
    )
    music_source_health_service = MusicSourceHealthService(
        music_source_state_repository,
        auth_fail_threshold=settings.youtube_auth_fail_threshold,
        degrade_ttl_minutes=settings.youtube_degrade_ttl_minutes,
        healthcheck_enabled=settings.cookie_healthcheck_enabled,
    )
    resolver_strategy_registry: dict[str, MusicProviderResolverStrategy] = {
        "youtube_no_cookies": MusicProviderResolverStrategy(
            name="youtube_no_cookies",
            provider=youtube_music_provider,
            cookie_provider=None,
            respect_health_state=False,
        ),
    }
    download_strategy_registry: dict[str, MusicProviderDownloadStrategy] = {
        "remote_http": MusicProviderDownloadStrategy(
            name="remote_http",
            provider=remote_music_download_provider,
            cookie_provider=None,
            respect_health_state=False,
            skip_probe=remote_music_download_provider.skip_reason,
        ),
        "youtube_no_cookies": MusicProviderDownloadStrategy(
            name="youtube_no_cookies",
            provider=audio_download_client,
            cookie_provider=None,
            respect_health_state=False,
        ),
    }
    if cookies_file is not None:
        cookie_provider = StaticCookieFileProvider(
            cookies_file=cookies_file,
            health_service=music_source_health_service,
        )
        resolver_strategy_registry["youtube_cookies"] = MusicProviderResolverStrategy(
            name="youtube_cookies",
            provider=youtube_music_provider,
            cookie_provider=cookie_provider,
            respect_health_state=settings.cookie_healthcheck_enabled,
        )
        download_strategy_registry["youtube_cookies"] = MusicProviderDownloadStrategy(
            name="youtube_cookies",
            provider=audio_download_client,
            cookie_provider=cookie_provider,
            respect_health_state=settings.cookie_healthcheck_enabled,
        )
    ordered_resolver_strategies = tuple(
        resolver_strategy_registry[name]
        for name in settings.music_resolver_order_list
        if name in resolver_strategy_registry
    )
    if not ordered_resolver_strategies:
        ordered_resolver_strategies = (resolver_strategy_registry["youtube_no_cookies"],)
    ordered_download_strategies = tuple(
        download_strategy_registry[name]
        for name in settings.music_download_provider_order_list
        if name in download_strategy_registry
    )
    if not ordered_download_strategies:
        ordered_download_strategies = (
            download_strategy_registry["remote_http"],
            download_strategy_registry["youtube_no_cookies"],
        )
    music_acquisition_service = MusicAcquisitionService(
        resolver_strategies=ordered_resolver_strategies,
        download_strategies=ordered_download_strategies,
        metadata_provider=music_metadata_provider,
        max_candidates=settings.music_resolver_max_candidates,
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
        ffmpeg_adapter=ffmpeg_adapter,
        music_acquisition_service=music_acquisition_service,
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
