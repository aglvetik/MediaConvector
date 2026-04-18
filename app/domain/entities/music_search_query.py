from __future__ import annotations

from dataclasses import dataclass

from app.domain.entities.normalized_resource import NormalizedResource


@dataclass(slots=True, frozen=True)
class MusicSearchQuery:
    trigger: str
    raw_query: str
    normalized_query: str
    normalized_resource: NormalizedResource
