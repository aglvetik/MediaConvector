from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class TrackSearchCandidate:
    source_id: str
    source_url: str
    title: str
    uploader: str | None
    thumbnail_url: str | None
    duration_sec: int | None
    score: int
