from __future__ import annotations

from app.domain.entities.track_query import TrackQuery
from app.domain.policies import parse_track_trigger


class TrackTriggerService:
    def parse(self, text: str) -> TrackQuery | None:
        return parse_track_trigger(text)
