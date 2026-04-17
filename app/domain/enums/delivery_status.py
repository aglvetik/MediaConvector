from enum import StrEnum


class DeliveryStatus(StrEnum):
    SENT_VIDEO = "sent_video"
    SENT_AUDIO = "sent_audio"
    SENT_ALL = "sent_all"
    PARTIAL = "partial"
    FAILED = "failed"

