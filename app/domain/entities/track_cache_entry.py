from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class TrackCacheEntry:
    normalized_query: str
    file_path: str
    title: str
    uploader: str
    source_url: str
