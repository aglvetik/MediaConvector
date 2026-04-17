from enum import StrEnum


class CacheStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    PARTIAL = "partial"
    INVALID = "invalid"
    FAILED = "failed"

