from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app import messages
from app.application.services.cache_service import CacheService
from app.application.services.dedup_service import InFlightDedupService
from app.application.services.delivery_service import DeliveryService
from app.application.services.metrics_service import MetricsService
from app.domain.entities.cache_entry import CacheEntry
from app.domain.entities.download_job import DownloadJob
from app.domain.entities.media_request import MediaRequest
from app.domain.entities.media_result import MediaMetadata, MediaResult
from app.domain.enums.delivery_status import DeliveryStatus
from app.domain.enums.job_status import JobStatus
from app.domain.errors import AudioExtractionError, DownloadError, InvalidCachedMediaError
from app.domain.interfaces.provider import DownloaderProvider
from app.domain.interfaces.repositories import DownloadJobRepository
from app.infrastructure.logging import get_logger, log_event
from app.infrastructure.media import FfmpegAdapter
from app.infrastructure.temp import TempFileManager


@dataclass(slots=True)
class OwnerPipelineResult:
    media_result: MediaResult
    cache_entry: CacheEntry


class MediaPipelineService:
    def __init__(
        self,
        *,
        cache_service: CacheService,
        dedup_service: InFlightDedupService,
        delivery_service: DeliveryService,
        job_repository: DownloadJobRepository,
        ffmpeg_adapter: FfmpegAdapter,
        temp_file_manager: TempFileManager,
        metrics_service: MetricsService,
    ) -> None:
        self._cache_service = cache_service
        self._dedup_service = dedup_service
        self._delivery_service = delivery_service
        self._job_repository = job_repository
        self._ffmpeg_adapter = ffmpeg_adapter
        self._temp_file_manager = temp_file_manager
        self._metrics = metrics_service
        self._logger = get_logger(__name__)

    async def process(self, request: MediaRequest, provider: DownloaderProvider) -> MediaResult:
        cache_entry = await self._cache_service.get_reusable(
            request.normalized_resource.normalized_key,
            resource_type=request.normalized_resource.resource_type,
        )
        if cache_entry is not None:
            log_event(self._logger, 20, "cache_hit", request_id=request.request_id, normalized_key=cache_entry.normalized_key)
            result = await self._deliver_from_cache_with_recovery(request, provider, cache_entry)
            if result is not None:
                self._metrics.increment("cache_hit")
                return result

        self._metrics.increment("cache_miss")
        log_event(self._logger, 20, "cache_miss", request_id=request.request_id, normalized_key=request.normalized_resource.normalized_key)
        owner_result, joined = await self._dedup_service.run_or_join(
            request.normalized_resource.normalized_key,
            lambda: self._run_owner_pipeline(request, provider),
        )
        if joined:
            shared_cache = await self._cache_service.get_reusable(
                request.normalized_resource.normalized_key,
                resource_type=request.normalized_resource.resource_type,
            )
            if shared_cache is None:
                raise DownloadError("In-flight job finished without reusable cache.", temporary=True)
            result = await self._deliver_from_cache_with_recovery(request, provider, shared_cache)
            if result is None:
                raise DownloadError("Shared cache became invalid while serving a joined request.", temporary=True)
            return result
        return owner_result.media_result

    async def _deliver_from_cache_with_recovery(
        self,
        request: MediaRequest,
        provider: DownloaderProvider,
        cache_entry: CacheEntry,
    ) -> MediaResult | None:
        try:
            result = await self._delivery_service.deliver_from_cache(request, cache_entry)
            await self._cache_service.increment_hit(cache_entry.normalized_key)
            return result
        except InvalidCachedMediaError as exc:
            await self._cache_service.mark_invalid(cache_entry.normalized_key)
            if exc.context.get("media_kind") == "audio" and exc.context.get("video_sent"):
                refreshed = await self._refresh_missing_audio(request, provider, cache_entry)
                await self._cache_service.increment_hit(cache_entry.normalized_key)
                return refreshed
            return None

    async def _run_owner_pipeline(self, request: MediaRequest, provider: DownloaderProvider) -> OwnerPipelineResult:
        await self._cache_service.mark_processing(request.normalized_resource)
        job = await self._job_repository.create(
            DownloadJob(
                id=None,
                request_id=request.request_id,
                normalized_key=request.normalized_resource.normalized_key,
                status=JobStatus.RUNNING,
                chat_id=request.chat_id,
                user_id=request.user_id,
                original_url=request.normalized_resource.original_url,
                started_at=datetime.now(timezone.utc),
                finished_at=None,
                error_code=None,
                error_message=None,
            )
        )

        work_dir = await self._temp_file_manager.create_work_dir(request.request_id)
        try:
            if request.normalized_resource.resource_type == "photo_post":
                owner_result = await self._run_photo_post_pipeline(request, provider, work_dir)
            elif request.normalized_resource.resource_type == "music_only":
                owner_result = await self._run_audio_only_pipeline(request, provider, work_dir)
            else:
                owner_result = await self._run_video_pipeline(request, provider, work_dir)

            if owner_result.media_result.delivery_status == DeliveryStatus.FAILED:
                await self._job_repository.update_status(
                    job.request_id,
                    JobStatus.FAILED,
                    error_code="delivery_failed",
                    error_message=owner_result.media_result.user_notice or "Primary media delivery failed.",
                )
            else:
                await self._job_repository.update_status(job.request_id, JobStatus.COMPLETED)
            return owner_result
        except Exception as exc:
            await self._cache_service.save_failed(request.normalized_resource)
            await self._job_repository.update_status(
                job.request_id,
                JobStatus.FAILED,
                error_code=getattr(exc, "error_code", "pipeline_failed"),
                error_message=str(exc),
            )
            raise
        finally:
            await self._temp_file_manager.remove_dir(work_dir)

    async def _run_video_pipeline(
        self,
        request: MediaRequest,
        provider: DownloaderProvider,
        work_dir: Path,
    ) -> OwnerPipelineResult:
        metadata = await provider.fetch_metadata(request.normalized_resource)
        video_path = await provider.download_video(request.normalized_resource, work_dir)
        audio_path, audio_notice = await self._try_extract_audio(request, video_path, metadata, work_dir)
        media_result = await self._delivery_service.deliver_uploads(
            request,
            video_path,
            audio_path,
            missing_audio_notice=audio_notice or messages.NO_AUDIO_TRACK,
        )
        cache_entry = await self._cache_service.save_delivery_result(
            resource=request.normalized_resource,
            metadata=metadata,
            video_receipt=media_result.video_receipt,
            audio_receipt=media_result.audio_receipt,
            notice=media_result.user_notice,
        )
        return OwnerPipelineResult(media_result=media_result, cache_entry=cache_entry)

    async def _run_photo_post_pipeline(
        self,
        request: MediaRequest,
        provider: DownloaderProvider,
        work_dir: Path,
    ) -> OwnerPipelineResult:
        metadata = await provider.fetch_metadata(request.normalized_resource)
        photo_paths = await provider.download_images(request.normalized_resource, work_dir)
        audio_path = await provider.download_audio(request.normalized_resource, work_dir)
        media_result = await self._delivery_service.deliver_photo_post_uploads(
            request,
            photo_paths,
            audio_path,
            missing_audio_notice=messages.NO_AUDIO_TRACK,
        )
        cache_entry = await self._cache_service.save_photo_delivery_result(
            resource=request.normalized_resource,
            metadata=metadata,
            photo_receipts=media_result.photo_receipts,
            audio_receipt=media_result.audio_receipt,
            notice=media_result.user_notice,
        )
        return OwnerPipelineResult(media_result=media_result, cache_entry=cache_entry)

    async def _run_audio_only_pipeline(
        self,
        request: MediaRequest,
        provider: DownloaderProvider,
        work_dir: Path,
    ) -> OwnerPipelineResult:
        metadata = await provider.fetch_metadata(request.normalized_resource)
        log_event(
            self._logger,
            20,
            "telegram_send_audio_only_started",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
        )
        audio_path = await provider.download_audio(request.normalized_resource, work_dir)
        media_result = await self._delivery_service.deliver_audio_only(
            request,
            audio_path,
            missing_audio_notice=messages.NO_AUDIO_TRACK,
        )
        if media_result.audio_receipt is not None:
            cache_entry = await self._cache_service.save_audio_only_result(
                resource=request.normalized_resource,
                metadata=metadata,
                audio_receipt=media_result.audio_receipt,
            )
        else:
            cache_entry = await self._cache_service.save_failed(request.normalized_resource)
        log_event(
            self._logger,
            20,
            "telegram_send_audio_only_finished",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            success=media_result.audio_receipt is not None,
        )
        return OwnerPipelineResult(media_result=media_result, cache_entry=cache_entry)

    async def _refresh_missing_audio(
        self,
        request: MediaRequest,
        provider: DownloaderProvider,
        previous_entry: CacheEntry,
    ) -> MediaResult:
        owner_result, joined = await self._dedup_service.run_or_join(
            request.normalized_resource.normalized_key,
            lambda: self._refresh_audio_owner(request, provider, previous_entry),
        )
        if joined:
            refreshed = await self._cache_service.get_reusable_audio(request.normalized_resource.normalized_key)
            if refreshed is not None and refreshed.audio_file_id:
                return await self._delivery_service.deliver_audio_from_cache(request, refreshed.audio_file_id)
            await self._delivery_service.send_text(request.chat_id, messages.SEPARATE_AUDIO_SEND_FAILED, request.message_id)
            return MediaResult(
                delivery_status=DeliveryStatus.PARTIAL,
                cache_status=previous_entry.status,
                video_receipt=None,
                audio_receipt=None,
                has_audio=False,
                cache_hit=False,
                user_notice=messages.SEPARATE_AUDIO_SEND_FAILED,
            )
        return owner_result.media_result

    async def _refresh_audio_owner(
        self,
        request: MediaRequest,
        provider: DownloaderProvider,
        previous_entry: CacheEntry,
    ) -> OwnerPipelineResult:
        work_dir = await self._temp_file_manager.create_work_dir(f"{request.request_id}-audio")
        try:
            metadata = await provider.fetch_metadata(request.normalized_resource)
            audio_path: Path | None
            if request.normalized_resource.resource_type == "video":
                video_path = await provider.download_video(request.normalized_resource, work_dir)
                audio_path, _ = await self._try_extract_audio(request, video_path, metadata, work_dir)
            else:
                audio_path = await provider.download_audio(request.normalized_resource, work_dir)
            result = await self._delivery_service.deliver_audio_only(
                request,
                audio_path,
                missing_audio_notice=messages.NO_AUDIO_TRACK,
                primary_delivered=True,
            )
            cache_entry = await self._cache_service.save_audio_refresh(
                resource=request.normalized_resource,
                previous_entry=previous_entry,
                audio_receipt=result.audio_receipt,
                metadata=metadata,
            )
            return OwnerPipelineResult(media_result=result, cache_entry=cache_entry)
        except Exception:
            cache_entry = await self._cache_service.save_audio_refresh(
                resource=request.normalized_resource,
                previous_entry=previous_entry,
                audio_receipt=None,
                metadata=None,
            )
            return OwnerPipelineResult(
                media_result=MediaResult(
                    delivery_status=DeliveryStatus.PARTIAL,
                    cache_status=cache_entry.status,
                    video_receipt=None,
                    audio_receipt=None,
                    has_audio=False,
                    cache_hit=False,
                    user_notice=messages.SEPARATE_AUDIO_SEND_FAILED,
                ),
                cache_entry=cache_entry,
            )
        finally:
            await self._temp_file_manager.remove_dir(work_dir)

    async def _try_extract_audio(
        self,
        request: MediaRequest,
        video_path: Path,
        metadata: MediaMetadata | None,
        work_dir: Path,
    ) -> tuple[Path | None, str | None]:
        if metadata is not None and metadata.has_audio is False:
            return None, messages.NO_AUDIO_TRACK
        audio_path = work_dir / f"{request.normalized_resource.resource_id}.mp3"
        try:
            return (
                await self._ffmpeg_adapter.extract_audio(
                    video_path,
                    audio_path,
                    normalized_key=request.normalized_resource.normalized_key,
                ),
                None,
            )
        except AudioExtractionError as exc:
            if exc.error_code == "no_audio_track":
                return None, messages.NO_AUDIO_TRACK
            log_event(
                self._logger,
                30,
                "partial_delivery",
                request_id=request.request_id,
                normalized_key=request.normalized_resource.normalized_key,
                reason="audio_extract_failed",
                error_code=exc.error_code,
            )
            return None, messages.AUDIO_EXTRACTION_FAILED
