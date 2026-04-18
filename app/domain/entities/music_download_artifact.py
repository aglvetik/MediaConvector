from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.domain.entities.music_track import MusicTrack


@dataclass(slots=True, frozen=True)
class MusicDownloadArtifact:
    source_audio_path: Path
    provider_name: str
    title: str | None = None
    performer: str | None = None
    thumbnail_url: str | None = None
    canonical_url: str | None = None
    source_id: str | None = None
    source_name: str | None = None

    def apply_to_track(self, track: MusicTrack) -> MusicTrack:
        return MusicTrack(
            source_id=self.source_id or track.source_id,
            source_url=track.source_url,
            canonical_url=self.canonical_url or track.canonical_url,
            title=self.title or track.title,
            performer=self.performer if self.performer is not None else track.performer,
            duration_sec=track.duration_sec,
            thumbnail_url=self.thumbnail_url if self.thumbnail_url is not None else track.thumbnail_url,
            resolver_name=track.resolver_name,
            source_name=self.source_name or track.source_name,
            ranking=track.ranking,
        )
