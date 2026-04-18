from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class MusicTrack:
    source_id: str
    source_url: str
    canonical_url: str
    title: str
    performer: str | None = None
    duration_sec: int | None = None
    thumbnail_url: str | None = None
