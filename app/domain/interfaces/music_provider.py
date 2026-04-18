from __future__ import annotations

from typing import Protocol

from app.domain.entities.music_track import MusicTrack


class MusicSearchProvider(Protocol):
    provider_name: str

    async def search_best_match(self, query: str) -> MusicTrack | None:
        ...
