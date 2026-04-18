from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.enums.cache_status import CacheStatus
from app.domain.enums.platform import Platform


@dataclass(slots=True)
class CacheEntry:
    id: int | None
    platform: Platform
    normalized_key: str
    original_url: str
    canonical_url: str
    video_file_id: str | None
    audio_file_id: str | None
    video_file_unique_id: str | None
    audio_file_unique_id: str | None
    duration_sec: int | None
    video_size_bytes: int | None
    audio_size_bytes: int | None
    has_audio: bool
    status: CacheStatus
    is_valid: bool
    cache_version: int
    hit_count: int
    created_at: datetime | None
    updated_at: datetime | None
    last_hit_at: datetime | None

    @property
    def is_ready_for_video(self) -> bool:
        return self.is_valid and self.video_file_id is not None and self.status in {CacheStatus.READY, CacheStatus.PARTIAL}

    @property
    def is_ready_for_audio(self) -> bool:
        return self.is_valid and self.audio_file_id is not None and self.status in {CacheStatus.READY, CacheStatus.PARTIAL}
