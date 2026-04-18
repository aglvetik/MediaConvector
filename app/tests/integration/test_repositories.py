from datetime import datetime, timezone

from app.domain.entities.cache_entry import CacheEntry
from app.domain.entities.download_job import DownloadJob
from app.domain.enums.cache_status import CacheStatus
from app.domain.enums.job_status import JobStatus
from app.domain.enums.platform import Platform
from app.infrastructure.persistence.sqlite import SqlAlchemyCacheRepository, SqlAlchemyDownloadJobRepository, SqlAlchemyProcessedMessageRepository, SqlAlchemyRequestLogRepository


async def test_repository_roundtrip(database) -> None:
    cache_repo = SqlAlchemyCacheRepository(database)
    job_repo = SqlAlchemyDownloadJobRepository(database)
    processed_repo = SqlAlchemyProcessedMessageRepository(database)
    request_log_repo = SqlAlchemyRequestLogRepository(database)

    saved = await cache_repo.save_result(
        CacheEntry(
            id=None,
            platform=Platform.TIKTOK,
            normalized_key="tiktok:video:1",
            original_url="https://www.tiktok.com/@u/video/1",
            canonical_url="https://www.tiktok.com/@u/video/1",
            video_file_id="vid1",
            audio_file_id="aud1",
            video_file_unique_id="uvid1",
            audio_file_unique_id="uaud1",
            duration_sec=10,
            video_size_bytes=100,
            audio_size_bytes=10,
            has_audio=True,
            status=CacheStatus.READY,
            is_valid=True,
            cache_version=1,
            hit_count=0,
            created_at=None,
            updated_at=None,
            last_hit_at=None,
        )
    )
    fetched = await cache_repo.get_by_normalized_key("tiktok:video:1")
    assert fetched is not None
    assert fetched.video_file_id == "vid1"
    await cache_repo.increment_hit("tiktok:video:1")
    fetched = await cache_repo.get_by_normalized_key("tiktok:video:1")
    assert fetched.hit_count == 1
    assert fetched.is_ready_for_video is True

    created_job = await job_repo.create(
        DownloadJob(
            id=None,
            request_id="req-1",
            normalized_key="tiktok:video:1",
            status=JobStatus.RUNNING,
            chat_id=1,
            user_id=2,
            original_url=saved.original_url,
            started_at=datetime.now(timezone.utc),
            finished_at=None,
            error_code=None,
            error_message=None,
        )
    )
    await job_repo.update_status(created_job.request_id, JobStatus.COMPLETED)
    assert await processed_repo.exists(1, 100, "tiktok:video:1") is False
    assert await processed_repo.claim(1, 100, "tiktok:video:1") is True
    assert await processed_repo.exists(1, 100, "tiktok:video:1") is True
    assert await processed_repo.claim(1, 100, "tiktok:video:1") is False
    await processed_repo.mark_finished(1, 100, "tiktok:video:1", success=True)
    await request_log_repo.log_started("req-1", 1, 2, 100, "tiktok:video:1", saved.original_url)
    await request_log_repo.log_finished("req-1", success=True, delivery_status="sent_all", cache_hit=False)
    assert await request_log_repo.count_recent() == 1
