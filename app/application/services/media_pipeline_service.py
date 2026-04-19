from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Literal

import httpx

from app import messages
from app.application.services.cache_service import CacheService
from app.application.services.dedup_service import InFlightDedupService
from app.application.services.delivery_service import DeliveryService
from app.application.services.metrics_service import MetricsService
from app.domain.entities.cache_entry import CacheEntry
from app.domain.entities.download_job import DownloadJob
from app.domain.entities.media_request import MediaRequest
from app.domain.entities.media_result import MediaMetadata, MediaResult
from app.domain.entities.visual_media_entry import VisualMediaEntry
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


@dataclass(slots=True)
class PreparedAudioAsset:
    final_audio_path: Path
    source_audio_extension: str
    container_extension: str
    telegram_filename: str
    title: str | None
    performer: str | None
    duration_sec: int | None
    thumbnail_path: Path | None

    @property
    def file_path(self) -> Path:
        return self.final_audio_path

    @property
    def filename(self) -> str:
        return self.telegram_filename


@dataclass(slots=True)
class PreparedAudioResult:
    status: Literal["prepared", "not_available", "failed_non_fatal", "failed_fatal"]
    asset: PreparedAudioAsset | None = None
    notice: str | None = None
    error_code: str | None = None
    telegram_filename: str | None = None
    source_audio_extension: str | None = None
    final_audio_extension: str | None = None

    @property
    def is_prepared(self) -> bool:
        return self.status == "prepared" and self.asset is not None


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
        audio_result = await self._prepare_audio_from_video(
            request,
            video_path,
            metadata,
            work_dir,
        )
        media_result = await self._delivery_service.deliver_uploads(
            request,
            video_path,
            audio_result.asset.file_path if audio_result.is_prepared else None,
            audio_title=audio_result.asset.title if audio_result.is_prepared else None,
            audio_performer=audio_result.asset.performer if audio_result.is_prepared else None,
            audio_duration_sec=audio_result.asset.duration_sec if audio_result.is_prepared else None,
            audio_thumbnail_path=audio_result.asset.thumbnail_path if audio_result.is_prepared else None,
            audio_filename=audio_result.asset.filename if audio_result.is_prepared else audio_result.telegram_filename,
            audio_source_extension=(
                audio_result.asset.source_audio_extension if audio_result.is_prepared else audio_result.source_audio_extension
            ),
            audio_final_extension=(
                audio_result.asset.container_extension if audio_result.is_prepared else audio_result.final_audio_extension
            ),
            missing_audio_notice=audio_result.notice or messages.NO_AUDIO_TRACK,
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
        try:
            metadata = await provider.fetch_metadata(request.normalized_resource)
            photo_paths = await self._prepare_visual_entries(request, provider, work_dir)
            audio_expected = (
                request.normalized_resource.has_expected_audio
                if request.normalized_resource.has_expected_audio is not None
                else metadata.has_audio is not False
            )
            audio_result = PreparedAudioResult(status="not_available")
            missing_audio_notice: str | None = None
            if audio_expected:
                try:
                    source_audio_path = await provider.download_audio(request.normalized_resource, work_dir)
                    if source_audio_path is None:
                        audio_result = PreparedAudioResult(
                            status="not_available",
                            notice=messages.NO_AUDIO_TRACK,
                            error_code="no_audio_track",
                        )
                    else:
                        audio_result = await self._prepare_audio_delivery_asset(
                            request=request,
                            metadata=metadata,
                            source_path=source_audio_path,
                            work_dir=work_dir,
                            fatal_on_failure=False,
                            missing_notice=messages.NO_AUDIO_TRACK,
                            failure_notice=messages.SEPARATE_AUDIO_SEND_FAILED,
                            fallback_cover_path=photo_paths[0] if photo_paths else None,
                        )
                except Exception as exc:
                    audio_result = PreparedAudioResult(
                        status="failed_non_fatal",
                        notice=messages.SEPARATE_AUDIO_SEND_FAILED,
                        error_code=getattr(exc, "error_code", "download_failed"),
                    )
                if audio_result.status in {"failed_non_fatal", "failed_fatal"}:
                    log_event(
                        self._logger,
                        30,
                        "optional_audio_failed",
                        request_id=request.request_id,
                        normalized_key=request.normalized_resource.normalized_key,
                        source_type=request.normalized_resource.platform.value,
                        error_code=audio_result.error_code or "audio_prepare_failed",
                    )
                missing_audio_notice = audio_result.notice
            media_result = await self._delivery_service.deliver_photo_post_uploads(
                request,
                photo_paths,
                audio_result.asset.file_path if audio_result.is_prepared else None,
                audio_expected=audio_expected,
                missing_audio_notice=missing_audio_notice,
                audio_title=audio_result.asset.title if audio_result.is_prepared else None,
                audio_performer=audio_result.asset.performer if audio_result.is_prepared else None,
                audio_duration_sec=audio_result.asset.duration_sec if audio_result.is_prepared else None,
                audio_thumbnail_path=audio_result.asset.thumbnail_path if audio_result.is_prepared else None,
                audio_filename=audio_result.asset.filename if audio_result.is_prepared else audio_result.telegram_filename,
                audio_source_extension=(
                    audio_result.asset.source_audio_extension if audio_result.is_prepared else audio_result.source_audio_extension
                ),
                audio_final_extension=(
                    audio_result.asset.container_extension if audio_result.is_prepared else audio_result.final_audio_extension
                ),
            )
            cache_entry = await self._cache_service.save_photo_delivery_result(
                resource=request.normalized_resource,
                metadata=metadata,
                photo_receipts=media_result.photo_receipts,
                audio_receipt=media_result.audio_receipt,
                notice=media_result.user_notice,
            )
            return OwnerPipelineResult(media_result=media_result, cache_entry=cache_entry)
        except Exception:
            self._logger.exception("visual_pipeline_crash")
            raise

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
        source_audio_path = await provider.download_audio(request.normalized_resource, work_dir)
        if source_audio_path is None:
            audio_result = PreparedAudioResult(
                status="failed_fatal",
                notice=messages.TEMPORARY_DOWNLOAD_ERROR,
                error_code="audio_not_available",
            )
        else:
            audio_result = await self._prepare_audio_delivery_asset(
                request=request,
                metadata=metadata,
                source_path=source_audio_path,
                work_dir=work_dir,
                fatal_on_failure=True,
                missing_notice=messages.TEMPORARY_DOWNLOAD_ERROR,
                failure_notice=messages.TEMPORARY_DOWNLOAD_ERROR,
            )
        if source_audio_path is not None and not audio_result.is_prepared:
            log_event(
                self._logger,
                30,
                "audio_delivery_asset_unavailable",
                request_id=request.request_id,
                chat_id=request.chat_id,
                normalized_key=request.normalized_resource.normalized_key,
                resource_type=request.normalized_resource.resource_type,
                audio_filename=audio_result.telegram_filename,
                source_audio_extension=audio_result.source_audio_extension,
                final_audio_extension=audio_result.final_audio_extension,
                error_code=audio_result.error_code or "prepared_audio_missing",
            )
        media_result = await self._delivery_service.deliver_audio_only(
            request,
            audio_result.asset.file_path if audio_result.is_prepared else None,
            missing_audio_notice=audio_result.notice or messages.TEMPORARY_DOWNLOAD_ERROR,
            title=audio_result.asset.title if audio_result.is_prepared else None,
            performer=audio_result.asset.performer if audio_result.is_prepared else None,
            duration_sec=audio_result.asset.duration_sec if audio_result.is_prepared else None,
            thumbnail_path=audio_result.asset.thumbnail_path if audio_result.is_prepared else None,
            filename=audio_result.asset.filename if audio_result.is_prepared else audio_result.telegram_filename,
            source_audio_extension=(
                audio_result.asset.source_audio_extension if audio_result.is_prepared else audio_result.source_audio_extension
            ),
            final_audio_extension=(
                audio_result.asset.container_extension if audio_result.is_prepared else audio_result.final_audio_extension
            ),
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
            audio_result = PreparedAudioResult(status="not_available")
            if request.normalized_resource.resource_type == "video":
                video_path = await provider.download_video(request.normalized_resource, work_dir)
                audio_result = await self._prepare_audio_from_video(request, video_path, metadata, work_dir)
            else:
                source_audio_path = await provider.download_audio(request.normalized_resource, work_dir)
                if source_audio_path is not None:
                    audio_result = await self._prepare_audio_delivery_asset(
                        request=request,
                        metadata=metadata,
                        source_path=source_audio_path,
                        work_dir=work_dir,
                        fatal_on_failure=False,
                        missing_notice=messages.NO_AUDIO_TRACK,
                        failure_notice=messages.SEPARATE_AUDIO_SEND_FAILED,
                    )
            result = await self._delivery_service.deliver_audio_only(
                request,
                audio_result.asset.file_path if audio_result.is_prepared else None,
                missing_audio_notice=audio_result.notice or messages.NO_AUDIO_TRACK,
                primary_delivered=True,
                title=audio_result.asset.title if audio_result.is_prepared else None,
                performer=audio_result.asset.performer if audio_result.is_prepared else None,
                duration_sec=audio_result.asset.duration_sec if audio_result.is_prepared else None,
                thumbnail_path=audio_result.asset.thumbnail_path if audio_result.is_prepared else None,
                filename=audio_result.asset.filename if audio_result.is_prepared else audio_result.telegram_filename,
                source_audio_extension=(
                    audio_result.asset.source_audio_extension if audio_result.is_prepared else audio_result.source_audio_extension
                ),
                final_audio_extension=(
                    audio_result.asset.container_extension if audio_result.is_prepared else audio_result.final_audio_extension
                ),
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

    async def _prepare_audio_from_video(
        self,
        request: MediaRequest,
        video_path: Path,
        metadata: MediaMetadata | None,
        work_dir: Path,
        *,
        fallback_cover_path: Path | None = None,
    ) -> PreparedAudioResult:
        if metadata is not None and metadata.has_audio is False:
            return PreparedAudioResult(
                status="not_available",
                notice=messages.NO_AUDIO_TRACK,
                error_code="no_audio_track",
            )
        log_event(
            self._logger,
            20,
            "media_audio_extraction_started",
            request_id=request.request_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
        )
        result = await self._prepare_audio_delivery_asset(
            request=request,
            metadata=metadata,
            source_path=video_path,
            work_dir=work_dir,
            fatal_on_failure=False,
            missing_notice=messages.NO_AUDIO_TRACK,
            failure_notice=messages.AUDIO_EXTRACTION_FAILED,
            fallback_cover_path=fallback_cover_path,
        )
        log_event(
            self._logger,
            20 if result.is_prepared else 30,
            "media_audio_extraction_finished",
            request_id=request.request_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
            success=result.is_prepared,
            error_code=result.error_code,
        )
        if result.status == "failed_non_fatal":
            log_event(
                self._logger,
                30,
                "partial_delivery",
                request_id=request.request_id,
                normalized_key=request.normalized_resource.normalized_key,
                reason="audio_extract_failed",
                error_code=result.error_code,
            )
        return result

    async def _prepare_visual_entries(
        self,
        request: MediaRequest,
        provider: DownloaderProvider,
        work_dir: Path,
    ) -> tuple[Path, ...]:
        if request.normalized_resource.engine_name == "gallery-dl":
            log_event(
                self._logger,
                20,
                "gallery_artifact_initialized",
                request_id=request.request_id,
                normalized_key=request.normalized_resource.normalized_key,
                source_type=request.normalized_resource.platform.value,
                canonical_url=request.normalized_resource.canonical_url,
                image_count=request.normalized_resource.entry_count,
                has_expected_audio=request.normalized_resource.has_expected_audio,
            )
            raw_paths = await provider.download_images(request.normalized_resource, work_dir)
            normalized_paths = await self._normalize_visual_files(request, raw_paths, work_dir)
            log_event(
                self._logger,
                20,
                "gallery_files_normalized",
                request_id=request.request_id,
                normalized_key=request.normalized_resource.normalized_key,
                source_type=request.normalized_resource.platform.value,
                canonical_url=request.normalized_resource.canonical_url,
                image_count=len(raw_paths),
                valid_image_count=len(normalized_paths),
                skipped_image_count=max(len(raw_paths) - len(normalized_paths), 0),
            )
            log_event(
                self._logger,
                20,
                "gallery_prepared",
                request_id=request.request_id,
                normalized_key=request.normalized_resource.normalized_key,
                source_type=request.normalized_resource.platform.value,
                canonical_url=request.normalized_resource.canonical_url,
                image_count=len(raw_paths),
                valid_image_count=len(normalized_paths),
                skipped_image_count=max(len(raw_paths) - len(normalized_paths), 0),
            )
            if not normalized_paths:
                raise DownloadError(
                    "No visual entries could be prepared for delivery.",
                    temporary=True,
                    context={
                        "normalized_key": request.normalized_resource.normalized_key,
                        "image_count": len(raw_paths),
                    },
                )
            return normalized_paths

        entries = request.normalized_resource.image_entries or tuple(
            VisualMediaEntry(source_url=image_url, order=index)
            for index, image_url in enumerate(request.normalized_resource.image_urls, start=1)
        )
        log_event(
            self._logger,
            20,
            "gallery_artifact_built" if len(entries) > 1 else "visual_artifact_built",
            request_id=request.request_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
            canonical_url=request.normalized_resource.canonical_url,
            image_count=len(entries),
            has_expected_audio=request.normalized_resource.has_expected_audio,
        )

        valid_paths: list[Path] = []
        skipped_count = 0
        for entry in entries:
            log_event(
                self._logger,
                20,
                "image_download_started",
                request_id=request.request_id,
                normalized_key=request.normalized_resource.normalized_key,
                source_type=request.normalized_resource.platform.value,
                canonical_url=request.normalized_resource.canonical_url,
                image_index=entry.order,
                image_url=entry.source_url,
            )
            try:
                path = await provider.download_image_entry(
                    request.normalized_resource,
                    work_dir,
                    source_url=entry.source_url,
                    entry_index=entry.order,
                )
            except Exception as exc:
                skipped_count += 1
                context = getattr(exc, "context", {})
                log_event(
                    self._logger,
                    30,
                    "image_download_failed",
                    request_id=request.request_id,
                    normalized_key=request.normalized_resource.normalized_key,
                    source_type=request.normalized_resource.platform.value,
                    canonical_url=request.normalized_resource.canonical_url,
                    image_index=entry.order,
                    original_image_url=context.get("original_url", entry.source_url),
                    normalized_image_url=context.get("normalized_url", entry.source_url),
                    https_upgrade_attempted=context.get("https_upgrade_attempted", False),
                    status_code=context.get("status_code"),
                    exception=context.get("exception", str(exc)),
                    error_code=getattr(exc, "error_code", "download_failed"),
                )
                continue
            valid_paths.append(path)
            log_event(
                self._logger,
                20,
                "image_download_finished",
                request_id=request.request_id,
                normalized_key=request.normalized_resource.normalized_key,
                source_type=request.normalized_resource.platform.value,
                canonical_url=request.normalized_resource.canonical_url,
                image_index=entry.order,
                file_path=str(path),
            )

        valid_count = len(valid_paths)
        normalized_paths = await self._normalize_visual_files(request, tuple(valid_paths), work_dir)
        normalized_count = len(normalized_paths)
        log_event(
            self._logger,
            20,
            "gallery_prepared",
            request_id=request.request_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
            canonical_url=request.normalized_resource.canonical_url,
            image_count=len(entries),
            valid_image_count=normalized_count,
            skipped_image_count=skipped_count,
        )
        if skipped_count:
            log_event(
                self._logger,
                20,
                "gallery_partial_success",
                request_id=request.request_id,
                normalized_key=request.normalized_resource.normalized_key,
                source_type=request.normalized_resource.platform.value,
                canonical_url=request.normalized_resource.canonical_url,
                image_count=len(entries),
                valid_image_count=normalized_count,
                skipped_image_count=skipped_count,
            )
        if not normalized_paths:
            raise DownloadError(
                "No visual entries could be prepared for delivery.",
                temporary=True,
                context={
                    "normalized_key": request.normalized_resource.normalized_key,
                    "image_count": len(entries),
                },
            )
        return normalized_paths

    async def _normalize_visual_files(
        self,
        request: MediaRequest,
        paths: tuple[Path, ...],
        work_dir: Path,
    ) -> tuple[Path, ...]:
        normalized_paths: list[Path] = []
        skipped_count = 0
        for index, path in enumerate(paths, start=1):
            try:
                normalized_path = await self._normalize_visual_file(request, path, work_dir, index=index)
            except Exception as exc:
                skipped_count += 1
                log_event(
                    self._logger,
                    30,
                    "image_download_failed",
                    request_id=request.request_id,
                    normalized_key=request.normalized_resource.normalized_key,
                    source_type=request.normalized_resource.platform.value,
                    canonical_url=request.normalized_resource.canonical_url,
                    image_index=index,
                    original_image_url=str(path),
                    normalized_image_url=str(path),
                    https_upgrade_attempted=False,
                    status_code=None,
                    exception=str(exc),
                    error_code=getattr(exc, "error_code", "image_normalize_failed"),
                )
                continue
            normalized_paths.append(normalized_path)
        if skipped_count:
            log_event(
                self._logger,
                20,
                "gallery_partial_success",
                request_id=request.request_id,
                normalized_key=request.normalized_resource.normalized_key,
                source_type=request.normalized_resource.platform.value,
                canonical_url=request.normalized_resource.canonical_url,
                image_count=len(paths),
                valid_image_count=len(normalized_paths),
                skipped_image_count=skipped_count,
            )
        return tuple(normalized_paths)

    async def _normalize_visual_file(
        self,
        request: MediaRequest,
        path: Path,
        work_dir: Path,
        *,
        index: int,
    ) -> Path:
        suffix = path.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            return path
        if suffix not in {".png", ".webp", ".bmp", ".gif"}:
            return path
        output_path = work_dir / f"{request.normalized_resource.resource_id}-image-{index}.jpg"
        converted = await self._ffmpeg_adapter.normalize_image_to_jpg(
            path,
            output_path,
            normalized_key=request.normalized_resource.normalized_key,
        )
        log_event(
            self._logger,
            20,
            "image_converted_to_jpg",
            request_id=request.request_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
            original_path=str(path),
            converted_path=str(converted),
        )
        return converted

    async def _prepare_audio_delivery_asset(
        self,
        *,
        request: MediaRequest,
        metadata: MediaMetadata | None,
        source_path: Path,
        work_dir: Path,
        fatal_on_failure: bool,
        missing_notice: str,
        failure_notice: str,
        preferred_container: Literal["mp3", "source"] = "mp3",
        fallback_cover_path: Path | None = None,
    ) -> PreparedAudioResult:
        source_extension = self._resolve_audio_extension(source_path)
        final_extension = "mp3" if preferred_container == "mp3" else source_extension
        intended_filename = self._build_audio_filename(
            request,
            self._resolve_audio_title(request, metadata),
            self._resolve_audio_performer(request, metadata),
            extension=final_extension,
        )
        try:
            asset = await self._build_audio_delivery_asset(
                request=request,
                metadata=metadata,
                source_path=source_path,
                work_dir=work_dir,
                preferred_container=preferred_container,
                fallback_cover_path=fallback_cover_path,
            )
            mismatch_reason = self._validate_prepared_audio_asset(asset)
            if mismatch_reason is not None:
                log_event(
                    self._logger,
                    40,
                    "audio_prepared_asset_invalid",
                    request_id=request.request_id,
                    normalized_key=request.normalized_resource.normalized_key,
                    source_type=request.normalized_resource.platform.value,
                    final_audio_path=str(asset.final_audio_path),
                    audio_file_exists=asset.final_audio_path.exists(),
                    audio_file_size=asset.final_audio_path.stat().st_size if asset.final_audio_path.exists() else None,
                    telegram_filename=asset.telegram_filename,
                    source_audio_extension=asset.source_audio_extension,
                    final_audio_extension=asset.container_extension,
                    mismatch_reason=mismatch_reason,
                )
                return PreparedAudioResult(
                    status="failed_fatal" if fatal_on_failure else "failed_non_fatal",
                    notice=messages.TEMPORARY_DOWNLOAD_ERROR if fatal_on_failure else failure_notice,
                    error_code="prepared_audio_invalid",
                    telegram_filename=asset.telegram_filename,
                    source_audio_extension=asset.source_audio_extension,
                    final_audio_extension=asset.container_extension,
                )
            log_event(
                self._logger,
                20,
                "audio_metadata_prepared",
                request_id=request.request_id,
                normalized_key=request.normalized_resource.normalized_key,
                title=asset.title,
                performer=asset.performer,
                duration_sec=asset.duration_sec,
                thumbnail_available=asset.thumbnail_path is not None,
                audio_filename=asset.telegram_filename,
                source_audio_extension=asset.source_audio_extension,
                final_audio_extension=asset.container_extension,
                final_audio_path=str(asset.final_audio_path),
            )
            return PreparedAudioResult(
                status="prepared",
                asset=asset,
                telegram_filename=asset.telegram_filename,
                source_audio_extension=asset.source_audio_extension,
                final_audio_extension=asset.container_extension,
            )
        except AudioExtractionError as exc:
            result_status: Literal["not_available", "failed_non_fatal", "failed_fatal"]
            if exc.error_code == "no_audio_track":
                result_status = "failed_fatal" if fatal_on_failure else "not_available"
                notice = messages.TEMPORARY_DOWNLOAD_ERROR if fatal_on_failure else missing_notice
            else:
                result_status = "failed_fatal" if fatal_on_failure else "failed_non_fatal"
                notice = messages.TEMPORARY_DOWNLOAD_ERROR if fatal_on_failure else failure_notice
            return PreparedAudioResult(
                status=result_status,
                notice=notice,
                error_code=exc.error_code,
                telegram_filename=intended_filename,
                source_audio_extension=source_extension,
                final_audio_extension=final_extension,
            )
        except Exception as exc:
            log_event(
                self._logger,
                30,
                "audio_prepare_failed",
                request_id=request.request_id,
                normalized_key=request.normalized_resource.normalized_key,
                source_type=request.normalized_resource.platform.value,
                error_code=getattr(exc, "error_code", "audio_prepare_failed"),
                source_audio_path=str(source_path),
                audio_filename=intended_filename,
                source_audio_extension=source_extension,
                final_audio_extension=final_extension,
                exception_type=type(exc).__name__,
                exception_message=str(exc),
            )
            return PreparedAudioResult(
                status="failed_fatal" if fatal_on_failure else "failed_non_fatal",
                notice=messages.TEMPORARY_DOWNLOAD_ERROR if fatal_on_failure else failure_notice,
                error_code=getattr(exc, "error_code", "audio_prepare_failed"),
                telegram_filename=intended_filename,
                source_audio_extension=source_extension,
                final_audio_extension=final_extension,
            )

    async def _build_audio_delivery_asset(
        self,
        *,
        request: MediaRequest,
        metadata: MediaMetadata | None,
        source_path: Path,
        work_dir: Path,
        preferred_container: Literal["mp3", "source"] = "mp3",
        fallback_cover_path: Path | None = None,
    ) -> PreparedAudioAsset:
        title = self._resolve_audio_title(request, metadata)
        performer = self._resolve_audio_performer(request, metadata)
        duration_sec = metadata.duration_sec if metadata is not None else request.normalized_resource.duration_sec
        source_extension = self._resolve_audio_extension(source_path)
        final_extension = "mp3" if preferred_container == "mp3" else source_extension
        filename = self._build_audio_filename(request, title, performer, extension=final_extension)
        thumbnail_path = await self._prepare_audio_thumbnail(
            request=request,
            work_dir=work_dir,
            fallback_cover_path=fallback_cover_path,
        )
        output_path = work_dir / filename
        if preferred_container == "mp3":
            prepared = await self._ffmpeg_adapter.transcode_audio_to_mp3(
                source_path,
                output_path,
                normalized_key=request.normalized_resource.normalized_key,
                title=title,
                performer=performer,
                cover_path=thumbnail_path,
            )
            log_event(
                self._logger,
                20,
                "audio_tags_written",
                request_id=request.request_id,
                normalized_key=request.normalized_resource.normalized_key,
                file_path=str(prepared),
                title=title,
                performer=performer,
                audio_filename=filename,
                final_audio_extension=final_extension,
            )
        else:
            if source_path.resolve() != output_path.resolve():
                shutil.copy2(source_path, output_path)
            prepared = output_path
            log_event(
                self._logger,
                20,
                "audio_asset_prepared_without_transcode",
                request_id=request.request_id,
                normalized_key=request.normalized_resource.normalized_key,
                file_path=str(prepared),
                audio_filename=filename,
                final_audio_extension=final_extension,
            )
        return PreparedAudioAsset(
            final_audio_path=prepared,
            source_audio_extension=source_extension,
            container_extension=final_extension,
            telegram_filename=filename,
            title=title,
            performer=performer,
            duration_sec=duration_sec,
            thumbnail_path=thumbnail_path,
        )

    async def _prepare_audio_thumbnail(
        self,
        *,
        request: MediaRequest,
        work_dir: Path,
        fallback_cover_path: Path | None = None,
    ) -> Path | None:
        source_path: Path | None = fallback_cover_path
        if source_path is None and request.normalized_resource.thumbnail_url:
            source_path = await self._download_thumbnail_asset(
                request=request,
                url=request.normalized_resource.thumbnail_url,
                work_dir=work_dir,
            )
        if source_path is None:
            return None
        output_path = work_dir / f"{request.normalized_resource.resource_id}-thumb.jpg"
        try:
            return await self._ffmpeg_adapter.prepare_audio_thumbnail(
                source_path,
                output_path,
                normalized_key=request.normalized_resource.normalized_key,
            )
        except Exception:
            return None

    async def _download_thumbnail_asset(
        self,
        *,
        request: MediaRequest,
        url: str,
        work_dir: Path,
    ) -> Path | None:
        suffix = Path(url.split("?", 1)[0]).suffix or ".jpg"
        target = work_dir / f"{request.normalized_resource.resource_id}-remote-thumb{suffix}"
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError:
            return None
        target.write_bytes(response.content)
        return target

    @staticmethod
    def _resolve_audio_title(request: MediaRequest, metadata: MediaMetadata | None) -> str:
        for candidate in (
            metadata.title if metadata is not None else None,
            request.normalized_resource.title,
        ):
            if candidate:
                cleaned = " ".join(candidate.split()).strip()
                if cleaned:
                    return cleaned
        platform_label = request.normalized_resource.platform.value.title()
        return f"{platform_label} audio"

    @staticmethod
    def _resolve_audio_performer(request: MediaRequest, metadata: MediaMetadata | None) -> str | None:
        for candidate in (
            metadata.author if metadata is not None else None,
            request.normalized_resource.author,
        ):
            if candidate:
                cleaned = " ".join(candidate.split()).strip()
                if cleaned:
                    return cleaned
        return request.normalized_resource.platform.value.title()

    def _build_audio_filename(
        self,
        request: MediaRequest,
        title: str | None,
        performer: str | None,
        *,
        extension: str,
    ) -> str:
        parts = [performer or "", title or ""]
        stem = " - ".join(part for part in parts if part).strip()
        if not stem:
            stem = f"{request.normalized_resource.platform.value}-audio"
        safe = "".join(character if character.isalnum() or character in {" ", "-", "_", "."} else "_" for character in stem)
        safe = " ".join(safe.split()).strip(" ._")
        if not safe:
            safe = f"{request.normalized_resource.platform.value}-audio"
        return f"{safe[:96]}.{extension}"

    @staticmethod
    def _resolve_audio_extension(source_path: Path) -> str:
        extension = source_path.suffix.lower().lstrip(".")
        return extension or "bin"

    @staticmethod
    def _validate_prepared_audio_asset(asset: PreparedAudioAsset) -> str | None:
        path = asset.final_audio_path
        if path is None:
            return "final_audio_path_missing"
        if not path.exists():
            return "final_audio_file_missing"
        if path.stat().st_size <= 0:
            return "final_audio_file_empty"
        path_extension = path.suffix.lower().lstrip(".")
        if asset.container_extension and path_extension != asset.container_extension.lower():
            return "container_extension_mismatch"
        filename_extension = Path(asset.telegram_filename).suffix.lower().lstrip(".")
        if filename_extension and path_extension and filename_extension != path_extension:
            return "telegram_filename_extension_mismatch"
        if asset.container_extension.lower() == "mp3" and path.suffix.lower() != ".mp3":
            return "final_audio_mp3_suffix_missing"
        return None
