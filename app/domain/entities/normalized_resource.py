from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums.platform import Platform


@dataclass(slots=True, frozen=True)
class NormalizedResource:
    platform: Platform
    resource_type: str
    resource_id: str
    normalized_key: str
    original_url: str
    canonical_url: str
    title: str | None = None
    author: str | None = None
    video_url: str | None = None
    audio_url: str | None = None
    image_urls: tuple[str, ...] = ()
    thumbnail_url: str | None = None
    duration_sec: int | None = None
