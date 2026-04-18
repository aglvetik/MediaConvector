from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class TrackQuery:
    trigger: str
    raw_query: str
    normalized_query: str
