from app.domain.enums.cache_status import CacheStatus
from app.domain.enums.delivery_status import DeliveryStatus


def determine_cache_status(*, video_sent: bool, audio_requested: bool, audio_sent: bool) -> CacheStatus:
    if not video_sent:
        return CacheStatus.FAILED
    if audio_requested and audio_sent:
        return CacheStatus.READY
    if audio_requested and not audio_sent:
        return CacheStatus.PARTIAL
    return CacheStatus.PARTIAL


def determine_delivery_status(*, video_sent: bool, audio_requested: bool, audio_sent: bool) -> DeliveryStatus:
    if not video_sent:
        return DeliveryStatus.FAILED
    if audio_requested and audio_sent:
        return DeliveryStatus.SENT_ALL
    if audio_requested and not audio_sent:
        return DeliveryStatus.PARTIAL
    return DeliveryStatus.SENT_VIDEO

