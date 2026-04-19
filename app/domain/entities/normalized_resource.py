from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums.platform import Platform
from app.domain.entities.visual_media_entry import VisualMediaEntry


@dataclass(slots=True, frozen=True)
class NormalizedResource:
    platform: Platform
    resource_type: str
    resource_id: str
    normalized_key: str
    original_url: str
    canonical_url: str
    media_kind: str = "video"
    title: str | None = None
    author: str | None = None
    video_url: str | None = None
    audio_url: str | None = None
    image_urls: tuple[str, ...] = ()
    image_entries: tuple[VisualMediaEntry, ...] = ()
    thumbnail_url: str | None = None
    duration_sec: int | None = None
    has_expected_audio: bool | None = None

    @property
    def entry_count(self) -> int:
        if self.image_entries:
            return len(self.image_entries)
        return len(self.image_urls)
