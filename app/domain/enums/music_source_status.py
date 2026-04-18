from enum import StrEnum


class MusicSourceStatus(StrEnum):
    HEALTHY = "healthy"
    SUSPECT = "suspect"
    BROKEN = "broken"
    MISSING = "missing"
