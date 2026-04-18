from __future__ import annotations

import logging

from app import messages
from app.domain.entities.music_search_query import MusicSearchQuery
from app.domain.errors import MusicQueryValidationError
from app.domain.policies import build_music_search_query, parse_music_trigger, validate_music_query
from app.infrastructure.logging import get_logger, log_event


class MusicSearchService:
    def __init__(self, *, max_query_length: int) -> None:
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
        validation = validate_music_query(raw_query)
        if len(validation.normalized_query) > self._max_query_length:
            raise MusicQueryValidationError(
                "Music query exceeds configured limit.",
                user_message=messages.MUSIC_QUERY_TOO_LONG,
                context={"trigger": trigger, "query_length": len(validation.normalized_query)},
            )
        if validation.meaningful_characters < 2:
            raise MusicQueryValidationError(
                "Music query is too short or lacks meaningful characters.",
                user_message=messages.MUSIC_QUERY_TOO_SHORT,
                context={
                    "trigger": trigger,
                    "meaningful_characters": validation.meaningful_characters,
                },
            )
        query = build_music_search_query(trigger, raw_query)
        log_event(
            self._logger,
            logging.INFO,
            "music_query_detected",
            trigger=query.trigger,
            normalized_key=query.normalized_resource.normalized_key,
            normalized_query=query.normalized_query,
        )
        return query
