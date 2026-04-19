from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums.platform import Platform


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
    image_sources: tuple[str, ...] = ()
