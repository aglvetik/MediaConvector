from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError

from app.domain.entities.cache_entry import CacheEntry
from app.domain.entities.download_job import DownloadJob
from app.domain.enums.cache_status import CacheStatus
from app.domain.enums.job_status import JobStatus
from app.domain.enums.platform import Platform
from app.infrastructure.persistence.sqlite.models import DownloadJobModel, MediaCacheModel, ProcessedMessageModel, RequestLogModel
from app.infrastructure.persistence.sqlite.session import Database


def _to_cache_entity(model: MediaCacheModel) -> CacheEntry:
    return CacheEntry(
        id=model.id,
        platform=Platform(model.platform),
        normalized_key=model.normalized_key,
        original_url=model.original_url,
        canonical_url=model.canonical_url,
        video_file_id=model.video_file_id,
        audio_file_id=model.audio_file_id,
        video_file_unique_id=model.video_file_unique_id,
        audio_file_unique_id=model.audio_file_unique_id,
        duration_sec=model.duration_sec,
        video_size_bytes=model.video_size_bytes,
        audio_size_bytes=model.audio_size_bytes,
        has_audio=model.has_audio,
        status=CacheStatus(model.status),
        is_valid=model.is_valid,
        cache_version=model.cache_version,
        hit_count=model.hit_count,
        created_at=model.created_at,
        updated_at=model.updated_at,
        last_hit_at=model.last_hit_at,
        raw_query=model.raw_query,
        source_id=model.source_id,
        title=model.title,
        performer=model.performer,
        thumbnail_url=model.thumbnail_url,
        has_thumbnail=model.has_thumbnail,
        file_name=model.file_name,
    )


class SqlAlchemyCacheRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_by_normalized_key(self, normalized_key: str) -> CacheEntry | None:
        async with self._database.session() as session:
            result = await session.execute(select(MediaCacheModel).where(MediaCacheModel.normalized_key == normalized_key))
            model = result.scalar_one_or_none()
            return _to_cache_entity(model) if model else None

    async def upsert_processing(self, entry: CacheEntry) -> CacheEntry:
        async with self._database.session() as session:
            existing = await session.execute(select(MediaCacheModel).where(MediaCacheModel.normalized_key == entry.normalized_key))
            current = existing.scalar_one_or_none()
            version = current.cache_version if current else 1
            stmt = insert(MediaCacheModel).values(
                platform=entry.platform.value,
                normalized_key=entry.normalized_key,
                original_url=entry.original_url,
                canonical_url=entry.canonical_url,
                video_file_id=current.video_file_id if current else None,
                audio_file_id=current.audio_file_id if current else None,
                video_file_unique_id=current.video_file_unique_id if current else None,
                audio_file_unique_id=current.audio_file_unique_id if current else None,
                duration_sec=current.duration_sec if current else None,
                video_size_bytes=current.video_size_bytes if current else None,
                audio_size_bytes=current.audio_size_bytes if current else None,
                has_audio=current.has_audio if current else entry.has_audio,
                status=CacheStatus.PROCESSING.value,
                is_valid=True,
                cache_version=version,
                hit_count=current.hit_count if current else 0,
                last_hit_at=current.last_hit_at if current else None,
                raw_query=current.raw_query if current else entry.raw_query,
                source_id=current.source_id if current else entry.source_id,
                title=current.title if current else entry.title,
                performer=current.performer if current else entry.performer,
                thumbnail_url=current.thumbnail_url if current else entry.thumbnail_url,
                has_thumbnail=current.has_thumbnail if current else entry.has_thumbnail,
                file_name=current.file_name if current else entry.file_name,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[MediaCacheModel.normalized_key],
                set_={
                    "platform": entry.platform.value,
                    "original_url": entry.original_url,
                    "canonical_url": entry.canonical_url,
                    "status": CacheStatus.PROCESSING.value,
                    "is_valid": True,
                    "updated_at": datetime.now(timezone.utc),
                    "raw_query": current.raw_query if current else entry.raw_query,
                    "source_id": current.source_id if current else entry.source_id,
                    "title": current.title if current else entry.title,
                    "performer": current.performer if current else entry.performer,
                    "thumbnail_url": current.thumbnail_url if current else entry.thumbnail_url,
                    "has_thumbnail": current.has_thumbnail if current else entry.has_thumbnail,
                    "file_name": current.file_name if current else entry.file_name,
                },
            )
            await session.execute(stmt)
            await session.commit()
        updated = await self.get_by_normalized_key(entry.normalized_key)
        if updated is None:
            raise RuntimeError("Failed to upsert processing cache entry.")
        return updated

    async def save_result(self, entry: CacheEntry) -> CacheEntry:
        async with self._database.session() as session:
            existing_result = await session.execute(select(MediaCacheModel).where(MediaCacheModel.normalized_key == entry.normalized_key))
            current = existing_result.scalar_one_or_none()
            version = 1 if current is None else current.cache_version + 1
            stmt = insert(MediaCacheModel).values(
                platform=entry.platform.value,
                normalized_key=entry.normalized_key,
                original_url=entry.original_url,
                canonical_url=entry.canonical_url,
                video_file_id=entry.video_file_id,
                audio_file_id=entry.audio_file_id,
                video_file_unique_id=entry.video_file_unique_id,
                audio_file_unique_id=entry.audio_file_unique_id,
                duration_sec=entry.duration_sec,
                video_size_bytes=entry.video_size_bytes,
                audio_size_bytes=entry.audio_size_bytes,
                has_audio=entry.has_audio,
                status=entry.status.value,
                is_valid=entry.is_valid,
                cache_version=version,
                hit_count=current.hit_count if current else entry.hit_count,
                last_hit_at=entry.last_hit_at,
                raw_query=entry.raw_query,
                source_id=entry.source_id,
                title=entry.title,
                performer=entry.performer,
                thumbnail_url=entry.thumbnail_url,
                has_thumbnail=entry.has_thumbnail,
                file_name=entry.file_name,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[MediaCacheModel.normalized_key],
                set_={
                    "platform": entry.platform.value,
                    "original_url": entry.original_url,
                    "canonical_url": entry.canonical_url,
                    "video_file_id": entry.video_file_id,
                    "audio_file_id": entry.audio_file_id,
                    "video_file_unique_id": entry.video_file_unique_id,
                    "audio_file_unique_id": entry.audio_file_unique_id,
                    "duration_sec": entry.duration_sec,
                    "video_size_bytes": entry.video_size_bytes,
                    "audio_size_bytes": entry.audio_size_bytes,
                    "has_audio": entry.has_audio,
                    "status": entry.status.value,
                    "is_valid": entry.is_valid,
                    "cache_version": version,
                    "last_hit_at": entry.last_hit_at,
                    "updated_at": datetime.now(timezone.utc),
                    "raw_query": entry.raw_query,
                    "source_id": entry.source_id,
                    "title": entry.title,
                    "performer": entry.performer,
                    "thumbnail_url": entry.thumbnail_url,
                    "has_thumbnail": entry.has_thumbnail,
                    "file_name": entry.file_name,
                },
            )
            await session.execute(stmt)
            await session.commit()
        saved = await self.get_by_normalized_key(entry.normalized_key)
        if saved is None:
            raise RuntimeError("Failed to save media cache entry.")
        return saved

    async def mark_invalid(self, normalized_key: str) -> None:
        async with self._database.session() as session:
            await session.execute(
                update(MediaCacheModel)
                .where(MediaCacheModel.normalized_key == normalized_key)
                .values(status=CacheStatus.INVALID.value, is_valid=False, updated_at=datetime.now(timezone.utc))
            )
            await session.commit()

    async def increment_hit(self, normalized_key: str) -> None:
        async with self._database.session() as session:
            await session.execute(
                update(MediaCacheModel)
                .where(MediaCacheModel.normalized_key == normalized_key)
                .values(
                    hit_count=MediaCacheModel.hit_count + 1,
                    last_hit_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

    async def count_by_status(self) -> dict[CacheStatus, int]:
        async with self._database.session() as session:
            result = await session.execute(select(MediaCacheModel.status, func.count()).group_by(MediaCacheModel.status))
            stats: dict[CacheStatus, int] = defaultdict(int)
            for status, count in result.all():
                stats[CacheStatus(status)] = count
            return dict(stats)


class SqlAlchemyDownloadJobRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def create(self, job: DownloadJob) -> DownloadJob:
        async with self._database.session() as session:
            model = DownloadJobModel(
                request_id=job.request_id,
                normalized_key=job.normalized_key,
                status=job.status.value,
                chat_id=job.chat_id,
                user_id=job.user_id,
                original_url=job.original_url,
                started_at=job.started_at or datetime.now(timezone.utc),
                finished_at=job.finished_at,
                error_code=job.error_code,
                error_message=job.error_message,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return DownloadJob(
                id=model.id,
                request_id=model.request_id,
                normalized_key=model.normalized_key,
                status=JobStatus(model.status),
                chat_id=model.chat_id,
                user_id=model.user_id,
                original_url=model.original_url,
                started_at=model.started_at,
                finished_at=model.finished_at,
                error_code=model.error_code,
                error_message=model.error_message,
            )

    async def update_status(
        self,
        request_id: str,
        status: JobStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        async with self._database.session() as session:
            values: dict[str, object] = {
                "status": status.value,
                "updated_at": datetime.now(timezone.utc),
            }
            if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                values["finished_at"] = datetime.now(timezone.utc)
            if error_code is not None:
                values["error_code"] = error_code
            if error_message is not None:
                values["error_message"] = error_message
            await session.execute(update(DownloadJobModel).where(DownloadJobModel.request_id == request_id).values(**values))
            await session.commit()

    async def count_stuck_jobs(self, stale_after_minutes: int) -> int:
        threshold = datetime.now(timezone.utc) - timedelta(minutes=stale_after_minutes)
        async with self._database.session() as session:
            result = await session.execute(
                select(func.count()).where(
                    DownloadJobModel.status == JobStatus.RUNNING.value,
                    DownloadJobModel.started_at < threshold,
                )
            )
            return int(result.scalar_one())

    async def mark_stale_jobs_failed(self, stale_after_minutes: int) -> int:
        threshold = datetime.now(timezone.utc) - timedelta(minutes=stale_after_minutes)
        async with self._database.session() as session:
            result = await session.execute(
                update(DownloadJobModel)
                .where(DownloadJobModel.status == JobStatus.RUNNING.value, DownloadJobModel.started_at < threshold)
                .values(
                    status=JobStatus.FAILED.value,
                    error_code="stale_job",
                    error_message="Marked failed by cleanup worker.",
                    finished_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
            return result.rowcount or 0


class SqlAlchemyProcessedMessageRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def exists(self, chat_id: int, message_id: int, normalized_key: str) -> bool:
        async with self._database.session() as session:
            result = await session.execute(
                select(func.count()).where(
                    ProcessedMessageModel.chat_id == chat_id,
                    ProcessedMessageModel.message_id == message_id,
                    ProcessedMessageModel.normalized_key == normalized_key,
                )
            )
            return bool(result.scalar_one())

    async def claim(self, chat_id: int, message_id: int, normalized_key: str) -> bool:
        async with self._database.session() as session:
            model = ProcessedMessageModel(
                chat_id=chat_id,
                message_id=message_id,
                normalized_key=normalized_key,
                status="running",
            )
            session.add(model)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False
            return True

    async def mark_finished(self, chat_id: int, message_id: int, normalized_key: str, *, success: bool) -> None:
        async with self._database.session() as session:
            await session.execute(
                update(ProcessedMessageModel)
                .where(
                    ProcessedMessageModel.chat_id == chat_id,
                    ProcessedMessageModel.message_id == message_id,
                    ProcessedMessageModel.normalized_key == normalized_key,
                )
                .values(
                    status="completed" if success else "failed",
                    finished_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()


class SqlAlchemyRequestLogRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def log_started(
        self,
        request_id: str,
        chat_id: int,
        user_id: int,
        message_id: int,
        normalized_key: str,
        original_url: str,
    ) -> None:
        async with self._database.session() as session:
            session.add(
                RequestLogModel(
                    request_id=request_id,
                    chat_id=chat_id,
                    user_id=user_id,
                    message_id=message_id,
                    normalized_key=normalized_key,
                    original_url=original_url,
                )
            )
            await session.commit()

    async def log_finished(
        self,
        request_id: str,
        *,
        success: bool,
        delivery_status: str,
        cache_hit: bool,
        error_code: str | None = None,
    ) -> None:
        async with self._database.session() as session:
            await session.execute(
                update(RequestLogModel)
                .where(RequestLogModel.request_id == request_id)
                .values(
                    success=success,
                    delivery_status=delivery_status,
                    cache_hit=cache_hit,
                    error_code=error_code,
                    finished_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

    async def count_recent(self) -> int:
        async with self._database.session() as session:
            result = await session.execute(select(func.count()).select_from(RequestLogModel))
            return int(result.scalar_one())
