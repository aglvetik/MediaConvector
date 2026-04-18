from __future__ import annotations

import logging

from app import messages
from app.domain.entities.music_search_query import MusicSearchQuery
from app.domain.entities.music_track import MusicTrack
from app.domain.errors import MusicNotFoundError, MusicQueryValidationError
from app.domain.interfaces.music_provider import MusicSearchProvider
from app.domain.policies import build_music_search_query, parse_music_trigger
from app.infrastructure.logging import get_logger, log_event


class MusicSearchService:
    def __init__(self, *, provider: MusicSearchProvider, max_query_length: int) -> None:
        self._provider = provider
        self._max_query_length = max_query_length
        self._logger = get_logger(__name__)

    def parse_message(self, text: str) -> MusicSearchQuery | None:
        parsed = parse_music_trigger(text)
        if parsed is None:
            return None
        trigger, raw_query = parsed
        if not raw_query:
            raise MusicQueryValidationError(
                "Music query is empty.",
                user_message=messages.music_empty_query(trigger),
                context={"trigger": trigger},
            )
        if len(raw_query) > self._max_query_length:
            raise MusicQueryValidationError(
                "Music query exceeds configured limit.",
                user_message=messages.MUSIC_QUERY_TOO_LONG,
                context={"trigger": trigger, "query_length": len(raw_query)},
            )
        query = build_music_search_query(trigger, raw_query)
        log_event(
            self._logger,
            logging.INFO,
            "music_query_detected",
            trigger=query.trigger,
            normalized_key=query.normalized_resource.normalized_key,
        )
        return query

    async def search_best_match(self, query: MusicSearchQuery) -> MusicTrack:
        track = await self._provider.search_best_match(query.raw_query)
        if track is None:
            raise MusicNotFoundError()
        log_event(
            self._logger,
            logging.INFO,
            "music_search_selected",
            normalized_key=query.normalized_resource.normalized_key,
            source_id=track.source_id,
            title=track.title,
            performer=track.performer,
        )
        return track
