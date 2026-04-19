from app.domain.enums.cache_status import CacheStatus
from app.domain.enums.delivery_status import DeliveryStatus
from app.domain.policies.partial_success import determine_cache_status, determine_delivery_status


def test_partial_status_when_audio_missing() -> None:
    assert determine_cache_status(video_sent=True, audio_requested=True, audio_sent=False) == CacheStatus.PARTIAL
    assert determine_delivery_status(video_sent=True, audio_requested=True, audio_sent=False) == DeliveryStatus.PARTIAL


def test_ready_status_when_video_and_audio_sent() -> None:
    assert determine_cache_status(video_sent=True, audio_requested=True, audio_sent=True) == CacheStatus.READY
    assert determine_delivery_status(video_sent=True, audio_requested=True, audio_sent=True) == DeliveryStatus.SENT_ALL


def test_ready_status_when_secondary_audio_not_requested() -> None:
    assert determine_cache_status(video_sent=True, audio_requested=False, audio_sent=False) == CacheStatus.READY
    assert determine_delivery_status(video_sent=True, audio_requested=False, audio_sent=False) == DeliveryStatus.SENT_VIDEO
