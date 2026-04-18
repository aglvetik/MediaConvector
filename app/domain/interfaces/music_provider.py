from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.domain.entities.music_download_artifact import MusicDownloadArtifact
from app.domain.entities.music_search_query import MusicSearchQuery
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


class MusicDownloadProvider(Protocol):
    provider_name: str

    async def download_track_audio(
        self,
        query: MusicSearchQuery,
        candidate: MusicTrack,
        work_dir: Path,
        *,
        cookies_file: Path | None = None,
    ) -> MusicDownloadArtifact:
        ...


class MusicMetadataProvider(Protocol):
    provider_name: str

    async def download_thumbnail(
        self,
        thumbnail_url: str,
        work_dir: Path,
        *,
        fallback_stem: str,
    ) -> Path | None:
        ...
