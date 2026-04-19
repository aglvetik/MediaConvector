from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums.platform import Platform
from app.domain.entities.visual_media_entry import VisualMediaEntry


@dataclass(slots=True, frozen=True)
class SourceMediaArtifact:
    source_type: Platform
    canonical_url: str
    media_kind: str
    source_id: str
    title: str | None = None
    uploader: str | None = None
    thumbnail_url: str | None = None
    duration_sec: int | None = None
    audio_source: str | None = None
    has_expected_audio: bool | None = None
    image_sources: tuple[str, ...] = ()
    image_entries: tuple[VisualMediaEntry, ...] = ()

    @property
    def entry_count(self) -> int:
        if self.image_entries:
            return len(self.image_entries)
        return len(self.image_sources)
