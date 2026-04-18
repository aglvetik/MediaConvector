from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from app.domain.entities.music_search_query import MusicSearchQuery
from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.enums.platform import Platform
from app.domain.policies.cache_key import build_cache_key

MUSIC_TRIGGERS = ("найти", "трек", "песня")


@dataclass(slots=True, frozen=True)
class MusicQueryValidationResult:
    normalized_query: str
    meaningful_characters: int


def parse_music_trigger(text: str) -> tuple[str, str] | None:
    normalized_text = unicodedata.normalize("NFKC", text).strip()
    if not normalized_text:
        return None
    parts = normalized_text.split(maxsplit=1)
    trigger = parts[0].casefold()
    if trigger not in MUSIC_TRIGGERS:
        return None
    query = parts[1].strip() if len(parts) > 1 else ""
    return trigger, query


def normalize_music_query(query: str) -> str:
    normalized = unicodedata.normalize("NFKC", query)
    return " ".join(normalized.casefold().split())


def validate_music_query(query: str) -> MusicQueryValidationResult:
    normalized_query = normalize_music_query(query)
    meaningful_characters = sum(1 for character in normalized_query if character.isalnum())
    return MusicQueryValidationResult(
        normalized_query=normalized_query,
        meaningful_characters=meaningful_characters,
    )


def build_music_search_query(trigger: str, raw_query: str) -> MusicSearchQuery:
    normalized_query = validate_music_query(raw_query).normalized_query
    normalized_resource = NormalizedResource(
        platform=Platform.MUSIC,
        resource_type="ytm",
        resource_id=normalized_query,
        normalized_key=build_cache_key(Platform.MUSIC, "ytm", normalized_query),
        original_url=raw_query,
        canonical_url=f"ytmusic:search:{normalized_query}",
    )
    return MusicSearchQuery(
        trigger=trigger,
        raw_query=raw_query,
        normalized_query=normalized_query,
        normalized_resource=normalized_resource,
    )
