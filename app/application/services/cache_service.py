from __future__ import annotations

from app.domain.entities.cache_entry import CacheEntry
from app.domain.entities.media_result import DeliveryReceipt, MediaMetadata
from app.domain.entities.music_track import MusicTrack
from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.enums.cache_status import CacheStatus
from app.domain.interfaces.repositories import CacheRepository
from app.infrastructure.logging import get_logger, log_event


class CacheService:
    def __init__(self, repository: CacheRepository) -> None:
        self._repository = repository
        self._logger = get_logger(__name__)

    async def get_reusable(self, normalized_key: str) -> CacheEntry | None:
        entry = await self._repository.get_by_normalized_key(normalized_key)
        if entry is None or not entry.is_ready_for_video:
            return None
        return entry

    async def get_entry(self, normalized_key: str) -> CacheEntry | None:
        return await self._repository.get_by_normalized_key(normalized_key)

    async def get_reusable_audio(self, normalized_key: str) -> CacheEntry | None:
        entry = await self._repository.get_by_normalized_key(normalized_key)
        if entry is None or not entry.is_ready_for_audio:
            return None
        return entry

    async def mark_processing(self, resource: NormalizedResource) -> CacheEntry:
        entry = CacheEntry(
            id=None,
            platform=resource.platform,
            normalized_key=resource.normalized_key,
            original_url=resource.original_url,
            canonical_url=resource.canonical_url,
            video_file_id=None,
            audio_file_id=None,
            video_file_unique_id=None,
            audio_file_unique_id=None,
            duration_sec=None,
            video_size_bytes=None,
            audio_size_bytes=None,
            has_audio=False,
            status=CacheStatus.PROCESSING,
            is_valid=True,
            cache_version=1,
            hit_count=0,
            created_at=None,
            updated_at=None,
            last_hit_at=None,
        )
        return await self._repository.upsert_processing(entry)

    async def save_delivery_result(
        self,
        *,
        resource: NormalizedResource,
        metadata: MediaMetadata | None,
        video_receipt: DeliveryReceipt,
        audio_receipt: DeliveryReceipt | None,
        previous_entry: CacheEntry | None = None,
        notice: str | None = None,
    ) -> CacheEntry:
        source_has_audio = self._resolve_source_has_audio(metadata=metadata, previous_entry=previous_entry, audio_receipt=audio_receipt)
        status = CacheStatus.READY if source_has_audio and audio_receipt is not None else CacheStatus.PARTIAL
        entry = CacheEntry(
            id=previous_entry.id if previous_entry else None,
            platform=resource.platform,
            normalized_key=resource.normalized_key,
            original_url=resource.original_url,
            canonical_url=resource.canonical_url,
            video_file_id=video_receipt.file_id,
            audio_file_id=audio_receipt.file_id if audio_receipt else None,
            video_file_unique_id=video_receipt.file_unique_id,
            audio_file_unique_id=audio_receipt.file_unique_id if audio_receipt else None,
            duration_sec=metadata.duration_sec if metadata else None,
            video_size_bytes=video_receipt.size_bytes or (metadata.size_bytes if metadata else None),
            audio_size_bytes=audio_receipt.size_bytes if audio_receipt else None,
            has_audio=source_has_audio,
            status=status,
            is_valid=True,
            cache_version=previous_entry.cache_version if previous_entry else 1,
            hit_count=previous_entry.hit_count if previous_entry else 0,
            created_at=previous_entry.created_at if previous_entry else None,
            updated_at=None,
            last_hit_at=previous_entry.last_hit_at if previous_entry else None,
        )
        saved = await self._repository.save_result(entry)
        log_event(
            self._logger,
            20,
            "cache_saved",
            normalized_key=resource.normalized_key,
            status=saved.status.value,
            has_audio=saved.has_audio,
            notice=notice,
        )
        return saved

    async def save_music_result(
        self,
        *,
        resource: NormalizedResource,
        raw_query: str,
        track: MusicTrack,
        audio_receipt: DeliveryReceipt | None,
        file_name: str,
        has_thumbnail: bool,
        previous_entry: CacheEntry | None = None,
    ) -> CacheEntry:
        entry = CacheEntry(
            id=previous_entry.id if previous_entry else None,
            platform=resource.platform,
            normalized_key=resource.normalized_key,
            original_url=raw_query,
            canonical_url=track.canonical_url,
            video_file_id=None,
            audio_file_id=audio_receipt.file_id if audio_receipt else None,
            video_file_unique_id=None,
            audio_file_unique_id=audio_receipt.file_unique_id if audio_receipt else None,
            duration_sec=track.duration_sec,
            video_size_bytes=None,
            audio_size_bytes=audio_receipt.size_bytes if audio_receipt else None,
            has_audio=audio_receipt is not None,
            status=CacheStatus.READY if audio_receipt is not None else CacheStatus.FAILED,
            is_valid=audio_receipt is not None,
            cache_version=previous_entry.cache_version if previous_entry else 1,
            hit_count=previous_entry.hit_count if previous_entry else 0,
            created_at=previous_entry.created_at if previous_entry else None,
            updated_at=None,
            last_hit_at=previous_entry.last_hit_at if previous_entry else None,
            raw_query=raw_query,
            source_id=track.source_id,
            title=track.title,
            performer=track.performer,
            thumbnail_url=track.thumbnail_url,
            has_thumbnail=has_thumbnail,
            file_name=file_name,
        )
        saved = await self._repository.save_result(entry)
        log_event(
            self._logger,
            20,
            "cache_saved",
            normalized_key=resource.normalized_key,
            status=saved.status.value,
            source_id=saved.source_id,
        )
        return saved

    async def save_audio_refresh(
        self,
        *,
        resource: NormalizedResource,
        previous_entry: CacheEntry,
        audio_receipt: DeliveryReceipt | None,
        metadata: MediaMetadata | None = None,
    ) -> CacheEntry:
        source_has_audio = self._resolve_source_has_audio(metadata=metadata, previous_entry=previous_entry, audio_receipt=audio_receipt)
        entry = CacheEntry(
            id=previous_entry.id,
            platform=resource.platform,
            normalized_key=resource.normalized_key,
            original_url=resource.original_url,
            canonical_url=resource.canonical_url,
            video_file_id=previous_entry.video_file_id,
            audio_file_id=audio_receipt.file_id if audio_receipt else None,
            video_file_unique_id=previous_entry.video_file_unique_id,
            audio_file_unique_id=audio_receipt.file_unique_id if audio_receipt else None,
            duration_sec=metadata.duration_sec if metadata else previous_entry.duration_sec,
            video_size_bytes=previous_entry.video_size_bytes,
            audio_size_bytes=audio_receipt.size_bytes if audio_receipt else None,
            has_audio=source_has_audio,
            status=CacheStatus.READY if source_has_audio and audio_receipt is not None else CacheStatus.PARTIAL,
            is_valid=True,
            cache_version=previous_entry.cache_version,
            hit_count=previous_entry.hit_count,
            created_at=previous_entry.created_at,
            updated_at=None,
            last_hit_at=previous_entry.last_hit_at,
        )
        return await self._repository.save_result(entry)

    async def save_failed(self, resource: NormalizedResource, previous_entry: CacheEntry | None = None) -> CacheEntry:
        entry = CacheEntry(
            id=previous_entry.id if previous_entry else None,
            platform=resource.platform,
            normalized_key=resource.normalized_key,
            original_url=resource.original_url,
            canonical_url=resource.canonical_url,
            video_file_id=previous_entry.video_file_id if previous_entry else None,
            audio_file_id=previous_entry.audio_file_id if previous_entry else None,
            video_file_unique_id=previous_entry.video_file_unique_id if previous_entry else None,
            audio_file_unique_id=previous_entry.audio_file_unique_id if previous_entry else None,
            duration_sec=previous_entry.duration_sec if previous_entry else None,
            video_size_bytes=previous_entry.video_size_bytes if previous_entry else None,
            audio_size_bytes=previous_entry.audio_size_bytes if previous_entry else None,
            has_audio=previous_entry.has_audio if previous_entry else False,
            status=CacheStatus.FAILED,
            is_valid=False,
            cache_version=previous_entry.cache_version if previous_entry else 1,
            hit_count=previous_entry.hit_count if previous_entry else 0,
            created_at=previous_entry.created_at if previous_entry else None,
            updated_at=None,
            last_hit_at=previous_entry.last_hit_at if previous_entry else None,
            raw_query=previous_entry.raw_query if previous_entry else None,
            source_id=previous_entry.source_id if previous_entry else None,
            title=previous_entry.title if previous_entry else None,
            performer=previous_entry.performer if previous_entry else None,
            thumbnail_url=previous_entry.thumbnail_url if previous_entry else None,
            has_thumbnail=previous_entry.has_thumbnail if previous_entry else False,
            file_name=previous_entry.file_name if previous_entry else None,
        )
        return await self._repository.save_result(entry)

    async def save_music_failed(
        self,
        *,
        resource: NormalizedResource,
        raw_query: str,
        previous_entry: CacheEntry | None = None,
    ) -> CacheEntry:
        entry = CacheEntry(
            id=previous_entry.id if previous_entry else None,
            platform=resource.platform,
            normalized_key=resource.normalized_key,
            original_url=raw_query,
            canonical_url=previous_entry.canonical_url if previous_entry else resource.canonical_url,
            video_file_id=None,
            audio_file_id=previous_entry.audio_file_id if previous_entry else None,
            video_file_unique_id=None,
            audio_file_unique_id=previous_entry.audio_file_unique_id if previous_entry else None,
            duration_sec=previous_entry.duration_sec if previous_entry else None,
            video_size_bytes=None,
            audio_size_bytes=previous_entry.audio_size_bytes if previous_entry else None,
            has_audio=previous_entry.has_audio if previous_entry else False,
            status=CacheStatus.FAILED,
            is_valid=False,
            cache_version=previous_entry.cache_version if previous_entry else 1,
            hit_count=previous_entry.hit_count if previous_entry else 0,
            created_at=previous_entry.created_at if previous_entry else None,
            updated_at=None,
            last_hit_at=previous_entry.last_hit_at if previous_entry else None,
            raw_query=raw_query,
            source_id=previous_entry.source_id if previous_entry else None,
            title=previous_entry.title if previous_entry else None,
            performer=previous_entry.performer if previous_entry else None,
            thumbnail_url=previous_entry.thumbnail_url if previous_entry else None,
            has_thumbnail=previous_entry.has_thumbnail if previous_entry else False,
            file_name=previous_entry.file_name if previous_entry else None,
        )
        return await self._repository.save_result(entry)

    async def mark_invalid(self, normalized_key: str) -> None:
        await self._repository.mark_invalid(normalized_key)
        log_event(self._logger, 30, "cache_invalidated", normalized_key=normalized_key)

    async def increment_hit(self, normalized_key: str) -> None:
        await self._repository.increment_hit(normalized_key)

    @staticmethod
    def _resolve_source_has_audio(
        *,
        metadata: MediaMetadata | None,
        previous_entry: CacheEntry | None,
        audio_receipt: DeliveryReceipt | None,
    ) -> bool:
        if metadata is not None and metadata.has_audio is not None:
            return metadata.has_audio
        if previous_entry is not None:
            return previous_entry.has_audio
        return audio_receipt is not None
