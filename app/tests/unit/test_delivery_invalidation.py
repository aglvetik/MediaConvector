import pytest

from app.application.services.delivery_service import DeliveryService
from app.domain.entities.cache_entry import CacheEntry
from app.domain.entities.media_request import MediaRequest
from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.enums.cache_status import CacheStatus
from app.domain.enums.platform import Platform
from app.domain.errors import InvalidCachedMediaError
from app.tests.fakes import FakeGateway


@pytest.mark.asyncio
async def test_delivery_rethrows_invalid_cached_audio_with_video_sent_context() -> None:
    gateway = FakeGateway()
    gateway.invalid_file_ids.add("bad-audio")
    service = DeliveryService(gateway)
    request = MediaRequest(
        request_id="r1",
        chat_id=1,
        user_id=1,
        message_id=10,
        chat_type="private",
        message_text="text",
        normalized_resource=NormalizedResource(
            platform=Platform.TIKTOK,
            resource_type="video",
            resource_id="123",
            normalized_key="tiktok:video:123",
            original_url="https://www.tiktok.com/@user/video/123",
            canonical_url="https://www.tiktok.com/@user/video/123",
        ),
    )
    cache_entry = CacheEntry(
        id=1,
        platform=Platform.TIKTOK,
        resource_type="video",
        normalized_key="tiktok:video:123",
        original_url=request.normalized_resource.original_url,
        canonical_url=request.normalized_resource.canonical_url,
        video_file_id="video-ok",
        audio_file_id="bad-audio",
        photo_file_ids=(),
        video_file_unique_id="uv",
        audio_file_unique_id="ua",
        photo_file_unique_ids=(),
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
    with pytest.raises(InvalidCachedMediaError) as exc_info:
        await service.deliver_from_cache(request, cache_entry)
    assert exc_info.value.context["video_sent"] is True


@pytest.mark.asyncio
async def test_delivery_from_cache_sends_cached_audio_without_logging_collision() -> None:
    gateway = FakeGateway()
    service = DeliveryService(gateway)
    request = MediaRequest(
        request_id="r2",
        chat_id=1,
        user_id=1,
        message_id=20,
        chat_type="private",
        message_text="text",
        normalized_resource=NormalizedResource(
            platform=Platform.LIKEE,
            resource_type="music_only",
            resource_id="audio-456",
            normalized_key="likee:music_only:audio-456",
            original_url="https://likee.video/@user/audio/audio-456",
            canonical_url="https://likee.video/@user/audio/audio-456",
            title="Original sound",
            author="Creator",
            duration_sec=15,
        ),
    )
    cache_entry = CacheEntry(
        id=2,
        platform=Platform.LIKEE,
        resource_type="music_only",
        normalized_key="likee:music_only:audio-456",
        original_url=request.normalized_resource.original_url,
        canonical_url=request.normalized_resource.canonical_url,
        video_file_id=None,
        audio_file_id="audio-ok",
        photo_file_ids=(),
        video_file_unique_id=None,
        audio_file_unique_id="ua",
        photo_file_unique_ids=(),
        duration_sec=15,
        video_size_bytes=None,
        audio_size_bytes=100,
        has_audio=True,
        status=CacheStatus.READY,
        is_valid=True,
        cache_version=1,
        hit_count=0,
        created_at=None,
        updated_at=None,
        last_hit_at=None,
    )

    result = await service.deliver_from_cache(request, cache_entry)

    assert result.audio_receipt is not None
    assert gateway.sent_audio_requests[-1].title == "Original sound"
    assert gateway.sent_audio_requests[-1].performer == "Creator"
