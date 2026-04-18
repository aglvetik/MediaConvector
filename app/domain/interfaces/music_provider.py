from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.domain.entities.music_track import MusicTrack


class MusicSearchProvider(Protocol):
    provider_name: str

    async def resolve_candidates(
        self,
        query: str,
        *,
        max_candidates: int,
        cookies_file: Path | None = None,
    ) -> list[MusicTrack]:
        ...
