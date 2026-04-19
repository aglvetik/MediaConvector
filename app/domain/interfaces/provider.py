from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.domain.entities.media_result import MediaMetadata
from app.domain.entities.normalized_resource import NormalizedResource


class DownloaderProvider(Protocol):
    platform_name: str

    def extract_first_url(self, text: str) -> str | None:
        ...

    def can_handle(self, url: str) -> bool:
        ...

    async def normalize(self, url: str) -> NormalizedResource:
        ...

    async def fetch_metadata(self, normalized: NormalizedResource) -> MediaMetadata:
        ...

    async def download_video(self, normalized: NormalizedResource, work_dir: Path) -> Path:
        ...

    async def download_audio(self, normalized: NormalizedResource, work_dir: Path) -> Path | None:
        ...

    async def download_image_entry(
        self,
        normalized: NormalizedResource,
        work_dir: Path,
        *,
        source_url: str,
        entry_index: int,
    ) -> Path:
        ...

    async def download_images(self, normalized: NormalizedResource, work_dir: Path) -> tuple[Path, ...]:
        ...
