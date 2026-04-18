from __future__ import annotations

import re

from app.domain.entities.track_query import TrackQuery
from app.domain.errors import InvalidTrackQueryError

_TRIGGER_PATTERN = re.compile(r"^\s*(?P<trigger>найти|трек|песня)\b(?P<query>.*)$", re.IGNORECASE)


def parse_track_trigger(text: str) -> TrackQuery | None:
    if not text:
        return None
    match = _TRIGGER_PATTERN.match(text)
    if not match:
        return None

    raw_query = match.group("query").strip()
    normalized_query = normalize_track_query(raw_query)
    if not normalized_query:
        raise InvalidTrackQueryError()

    meaningful_characters = sum(1 for char in normalized_query if char.isalnum())
    if meaningful_characters < 2:
        raise InvalidTrackQueryError()

    return TrackQuery(
        trigger=match.group("trigger").casefold(),
        raw_query=raw_query,
        normalized_query=normalized_query,
    )


def normalize_track_query(query: str) -> str:
    return " ".join(query.casefold().split()).strip()
