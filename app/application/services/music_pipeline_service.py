from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.domain.entities.cache_entry import CacheEntry
from app.domain.entities.download_job import DownloadJob
from app.domain.entities.media_request import MediaRequest
from app.domain.entities.media_result import MediaResult
from app.domain.entities.music_search_query import MusicSearchQuery
from app.domain.errors import AudioExtractionError, InvalidCachedMediaError, MusicDownloadError
from app.domain.enums.job_status import JobStatus
from app.domain.interfaces.repositories import DownloadJobRepository
from app.domain.policies import build_safe_file_stem, build_track_file_name
from app.infrastructure.downloaders.audio_download_client import AudioDownloadClient
from app.infrastructure.logging import get_logger, log_event
from app.infrastructure.media import FfmpegAdapter
from app.infrastructure.temp import TempFileManager

from app.application.services.cache_service import CacheService
from app.application.services.dedup_service import InFlightDedupService
from app.application.services.delivery_service import DeliveryService
from app.application.services.metrics_service import MetricsService
from app.application.services.music_search_service import MusicSearchService


@dataclass(slots=True)
class MusicOwnerPipelineResult:
    media_result: MediaResult
    cache_entry: CacheEntry


class MusicPipelineService:
    def __init__(
        self,
        *,
        cache_service: CacheService,
        dedup_service: InFlightDedupService,
        delivery_service: DeliveryService,
        job_repository: DownloadJobRepository,
        temp_file_manager: TempFileManager,
        audio_download_client: AudioDownloadClient,
        ffmpeg_adapter: FfmpegAdapter,
        music_search_service: MusicSearchService,
        metrics_service: MetricsService,
    ) -> None:
        self._cache_service = cache_service
        self._dedup_service = dedup_service
        self._delivery_service = delivery_service
        self._job_repository = job_repository
        self._temp_file_manager = temp_file_manager
        self._audio_download_client = audio_download_client
        self._ffmpeg_adapter = ffmpeg_adapter
        self._music_search_service = music_search_service
        self._metrics = metrics_service
        self._logger = get_logger(__name__)

    async def process(self, request: MediaRequest, query: MusicSearchQuery) -> MediaResult:
        cache_entry = await self._cache_service.get_reusable_audio(request.normalized_resource.normalized_key)
        if cache_entry is not None:
            log_event(self._logger, logging.INFO, "cache_hit", request_id=request.request_id, normalized_key=cache_entry.normalized_key)
            result = await self._deliver_from_cache_with_recovery(request, cache_entry)
            if result is not None:
                self._metrics.increment("music_cache_hit")
                return result

        self._metrics.increment("music_cache_miss")
        log_event(
            self._logger,
            logging.INFO,
            "cache_miss",
            request_id=request.request_id,
            normalized_key=request.normalized_resource.normalized_key,
        )
        owner_result, joined = await self._dedup_service.run_or_join(
            request.normalized_resource.normalized_key,
            lambda: self._run_owner_pipeline(request, query),
        )
        if joined:
            shared_cache = await self._cache_service.get_reusable_audio(request.normalized_resource.normalized_key)
            if shared_cache is None:
                raise MusicDownloadError("In-flight music job finished without reusable cache.")
            result = await self._deliver_from_cache_with_recovery(request, shared_cache)
            if result is None:
                raise MusicDownloadError("Shared music cache became invalid while serving a joined request.")
            return result
        return owner_result.media_result

    async def _deliver_from_cache_with_recovery(self, request: MediaRequest, cache_entry: CacheEntry) -> MediaResult | None:
        try:
            result = await self._delivery_service.deliver_music_from_cache(request, cache_entry)
            await self._cache_service.increment_hit(cache_entry.normalized_key)
            return result
        except InvalidCachedMediaError:
            await self._cache_service.mark_invalid(cache_entry.normalized_key)
            return None

    async def _run_owner_pipeline(self, request: MediaRequest, query: MusicSearchQuery) -> MusicOwnerPipelineResult:
        await self._cache_service.mark_processing(query.normalized_resource)
        job = await self._job_repository.create(
            DownloadJob(
                id=None,
                request_id=request.request_id,
                normalized_key=query.normalized_resource.normalized_key,
                status=JobStatus.RUNNING,
                chat_id=request.chat_id,
                user_id=request.user_id,
                original_url=query.raw_query,
                started_at=datetime.now(timezone.utc),
                finished_at=None,
                error_code=None,
                error_message=None,
            )
        )
        work_dir = await self._temp_file_manager.create_work_dir(f"{request.request_id}-music")
        try:
            track = await self._music_search_service.search_best_match(query)
            source_audio_path = await self._audio_download_client.download_audio_source(track, work_dir)
            file_name = build_track_file_name(track)
            output_stem = build_safe_file_stem(Path(file_name).stem, fallback=track.source_id)
            output_path = await self._transcode_audio(source_audio_path, work_dir / f"{output_stem}.mp3", request.normalized_resource.normalized_key, track.title, track.performer)
            thumbnail_path = await self._prepare_thumbnail(track, work_dir, request.normalized_resource.normalized_key)
            media_result = await self._delivery_service.deliver_music_upload(
                request,
                output_path,
                title=track.title,
                performer=track.performer,
                thumbnail_path=thumbnail_path,
                file_name=file_name,
            )
            cache_entry = await self._cache_service.save_music_result(
                resource=query.normalized_resource,
                raw_query=query.raw_query,
                track=track,
                audio_receipt=media_result.audio_receipt,
                file_name=file_name,
                has_thumbnail=thumbnail_path is not None,
            )
            await self._job_repository.update_status(job.request_id, JobStatus.COMPLETED)
            return MusicOwnerPipelineResult(media_result=media_result, cache_entry=cache_entry)
        except Exception as exc:
            previous_entry = await self._cache_service.get_entry(query.normalized_resource.normalized_key)
            await self._cache_service.save_music_failed(
                resource=query.normalized_resource,
                raw_query=query.raw_query,
                previous_entry=previous_entry,
            )
            await self._job_repository.update_status(
                job.request_id,
                JobStatus.FAILED,
                error_code=getattr(exc, "error_code", "music_pipeline_failed"),
                error_message=str(exc),
            )
            raise
        finally:
            await self._temp_file_manager.remove_dir(work_dir)

    async def _transcode_audio(
        self,
        source_audio_path: Path,
        output_path: Path,
        normalized_key: str,
        title: str,
        performer: str | None,
    ) -> Path:
        try:
            return await self._ffmpeg_adapter.transcode_audio_to_mp3(
                source_audio_path,
                output_path,
                normalized_key=normalized_key,
                title=title,
                performer=performer,
            )
        except AudioExtractionError as exc:
            raise MusicDownloadError(
                "Failed to transcode downloaded track audio.",
                context={"normalized_key": normalized_key, "error_code": exc.error_code},
            ) from exc

    async def _prepare_thumbnail(self, track, work_dir: Path, normalized_key: str) -> Path | None:
        if track.thumbnail_url is None:
            return None
        downloaded_thumbnail = await self._audio_download_client.download_thumbnail(track.thumbnail_url, work_dir, fallback_stem=track.source_id)
        if downloaded_thumbnail is None:
            return None
        output_path = work_dir / f"{build_safe_file_stem(track.source_id, fallback='cover')}-cover.jpg"
        try:
            return await self._ffmpeg_adapter.prepare_thumbnail(
                downloaded_thumbnail,
                output_path,
                normalized_key=normalized_key,
            )
        except Exception as exc:
            log_event(
                self._logger,
                logging.WARNING,
                "music_thumbnail_prepare_failed",
                normalized_key=normalized_key,
                error=str(exc),
            )
            return None
