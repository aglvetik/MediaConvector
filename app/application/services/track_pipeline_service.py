from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app import messages
from app.application.services.dedup_service import InFlightDedupService
from app.application.services.delivery_service import DeliveryService
from app.application.services.metrics_service import MetricsService
from app.domain.entities.media_request import MediaRequest
from app.domain.entities.media_result import MediaResult
from app.domain.entities.track_cache_entry import TrackCacheEntry
from app.domain.entities.track_query import TrackQuery
from app.domain.entities.track_search_candidate import TrackSearchCandidate
from app.domain.errors import AudioExtractionError, TrackDownloadError
from app.domain.policies import derive_track_metadata
from app.infrastructure.downloaders import YoutubeTrackClient
from app.infrastructure.logging import get_logger, log_event
from app.infrastructure.media import FfmpegAdapter
from app.infrastructure.persistence.json import JsonTrackCacheStore
from app.infrastructure.temp import TempFileManager


@dataclass(slots=True)
class TrackOwnerResult:
    media_result: MediaResult
    cache_entry: TrackCacheEntry | None


class TrackPipelineService:
    def __init__(
        self,
        *,
        delivery_service: DeliveryService,
        dedup_service: InFlightDedupService,
        ffmpeg_adapter: FfmpegAdapter,
        temp_file_manager: TempFileManager,
        track_client: YoutubeTrackClient,
        track_cache_store: JsonTrackCacheStore,
        metrics_service: MetricsService,
        enable_cover_embed: bool = True,
    ) -> None:
        self._delivery_service = delivery_service
        self._dedup_service = dedup_service
        self._ffmpeg_adapter = ffmpeg_adapter
        self._temp_file_manager = temp_file_manager
        self._track_client = track_client
        self._track_cache_store = track_cache_store
        self._metrics = metrics_service
        self._enable_cover_embed = enable_cover_embed
        self._logger = get_logger(__name__)

    async def process(self, request: MediaRequest, query: TrackQuery) -> MediaResult:
        cache_entry = await self._track_cache_store.get(query.normalized_query)
        if cache_entry is not None:
            cached_path = self._track_cache_store.resolve_cached_file(cache_entry)
            if cached_path.exists():
                log_event(self._logger, 20, "music_cache_hit", normalized_key=request.normalized_resource.normalized_key)
                self._metrics.increment("music_cache_hit")
                return await self._delivery_service.deliver_audio_only(
                    request,
                    cached_path,
                    title=cache_entry.title,
                    performer=cache_entry.uploader,
                    failure_notice=messages.TRACK_DOWNLOAD_FAILED,
                    cache_hit=True,
                )
            log_event(
                self._logger,
                20,
                "music_cache_miss",
                normalized_key=request.normalized_resource.normalized_key,
                reason="cached_file_missing",
            )

        self._metrics.increment("music_cache_miss")
        owner_result, joined = await self._dedup_service.run_or_join(
            request.normalized_resource.normalized_key,
            lambda: self._run_owner_pipeline(request, query, cache_entry),
        )
        if joined:
            shared_entry = await self._track_cache_store.get(query.normalized_query)
            if shared_entry is None:
                raise TrackDownloadError("Shared track processing finished without cache entry.")
            cached_path = self._track_cache_store.resolve_cached_file(shared_entry)
            if not cached_path.exists():
                raise TrackDownloadError("Shared track cache file is missing after processing.")
            return await self._delivery_service.deliver_audio_only(
                request,
                cached_path,
                title=shared_entry.title,
                performer=shared_entry.uploader,
                failure_notice=messages.TRACK_DOWNLOAD_FAILED,
                cache_hit=True,
            )
        return owner_result.media_result

    async def _run_owner_pipeline(
        self,
        request: MediaRequest,
        query: TrackQuery,
        cached_entry: TrackCacheEntry | None,
    ) -> TrackOwnerResult:
        work_dir = await self._temp_file_manager.create_work_dir(f"{request.request_id}-track")
        try:
            candidate = await self._resolve_candidate(request, query, cached_entry)
            title, performer = derive_track_metadata(candidate)
            source_path = await self._track_client.download_audio(
                candidate.source_url,
                work_dir,
                normalized_key=request.normalized_resource.normalized_key,
            )
            prepared_thumbnail = await self._prepare_thumbnail(candidate, work_dir, request)
            final_audio = await self._build_mp3(
                source_path=source_path,
                normalized_key=request.normalized_resource.normalized_key,
                title=title,
                performer=performer,
                prepared_thumbnail=prepared_thumbnail,
                destination=self._track_cache_store.build_target_path(query.normalized_query),
                work_dir=work_dir,
            )
            cache_entry = TrackCacheEntry(
                normalized_query=query.normalized_query,
                file_path=_to_cache_path(final_audio),
                title=title,
                uploader=performer,
                source_url=candidate.source_url,
            )
            await self._track_cache_store.set(cache_entry)
            media_result = await self._delivery_service.deliver_audio_only(
                request,
                final_audio,
                title=title,
                performer=performer,
                thumbnail_path=prepared_thumbnail,
                failure_notice=messages.TRACK_DOWNLOAD_FAILED,
            )
            return TrackOwnerResult(media_result=media_result, cache_entry=cache_entry)
        finally:
            await self._temp_file_manager.remove_dir(work_dir)

    async def _resolve_candidate(
        self,
        request: MediaRequest,
        query: TrackQuery,
        cached_entry: TrackCacheEntry | None,
    ) -> TrackSearchCandidate:
        if cached_entry is not None and cached_entry.source_url:
            return TrackSearchCandidate(
                source_id=query.normalized_query,
                source_url=cached_entry.source_url,
                title=cached_entry.title,
                uploader=cached_entry.uploader,
                thumbnail_url=None,
                duration_sec=None,
                score=0,
            )
        return await self._track_client.search(query.raw_query, normalized_key=request.normalized_resource.normalized_key)

    async def _prepare_thumbnail(
        self,
        candidate: TrackSearchCandidate,
        work_dir: Path,
        request: MediaRequest,
    ) -> Path | None:
        if not candidate.thumbnail_url:
            return None
        raw_thumbnail = work_dir / f"{candidate.source_id}-thumb"
        prepared_thumbnail = work_dir / f"{candidate.source_id}-thumb.jpg"
        try:
            await self._track_client.download_thumbnail(candidate.thumbnail_url, raw_thumbnail)
            return await self._ffmpeg_adapter.prepare_audio_thumbnail(
                raw_thumbnail,
                prepared_thumbnail,
                normalized_key=request.normalized_resource.normalized_key,
            )
        except Exception as exc:
            log_event(
                self._logger,
                30,
                "music_thumbnail_download_failed",
                normalized_key=request.normalized_resource.normalized_key,
                error=str(exc),
            )
            return None

    async def _build_mp3(
        self,
        *,
        source_path: Path,
        normalized_key: str,
        title: str,
        performer: str,
        prepared_thumbnail: Path | None,
        destination: Path,
        work_dir: Path,
    ) -> Path:
        temporary_output = work_dir / destination.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if self._enable_cover_embed and prepared_thumbnail is not None:
            try:
                await self._ffmpeg_adapter.transcode_audio_to_mp3(
                    source_path,
                    temporary_output,
                    normalized_key=normalized_key,
                    title=title,
                    performer=performer,
                    cover_path=prepared_thumbnail,
                )
            except AudioExtractionError as exc:
                log_event(
                    self._logger,
                    30,
                    "music_cover_embed_failed",
                    normalized_key=normalized_key,
                    error_code=exc.error_code,
                )
                await self._ffmpeg_adapter.transcode_audio_to_mp3(
                    source_path,
                    temporary_output,
                    normalized_key=normalized_key,
                    title=title,
                    performer=performer,
                    cover_path=None,
                )
        else:
            await self._ffmpeg_adapter.transcode_audio_to_mp3(
                source_path,
                temporary_output,
                normalized_key=normalized_key,
                title=title,
                performer=performer,
                cover_path=None,
            )
        temporary_output.replace(destination)
        return destination


def _to_cache_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)
