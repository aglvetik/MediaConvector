from __future__ import annotations

from pathlib import Path

from app.domain.entities.media_result import MediaMetadata
from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.enums.platform import Platform
from app.domain.interfaces.provider import DownloaderProvider
from app.infrastructure.logging import get_logger, log_event
from app.infrastructure.providers.engine_routing import select_engine_name
from app.infrastructure.providers.source_detection import detect_source_type, extract_first_supported_url


class RoutedUrlProvider:
    def __init__(
        self,
        *,
        platform: Platform,
        ytdlp_provider: DownloaderProvider,
        gallery_provider: DownloaderProvider,
    ) -> None:
        self.platform_name = platform.value
        self._platform = platform
        self._ytdlp_provider = ytdlp_provider
        self._gallery_provider = gallery_provider
        self._logger = get_logger(__name__)

    def extract_first_url(self, text: str) -> str | None:
        return extract_first_supported_url(text, self._platform)

    def can_handle(self, url: str) -> bool:
        return detect_source_type(url) == self._platform

    async def normalize(self, url: str) -> NormalizedResource:
        provider = self._provider_for_url(url)
        log_event(
            self._logger,
            20,
            "engine_routed",
            source_type=self._platform.value,
            canonical_url=url,
            engine_name="gallery-dl" if provider is self._gallery_provider else "yt-dlp",
        )
        normalized = await provider.normalize(url)
        return normalized

    async def fetch_metadata(self, normalized: NormalizedResource) -> MediaMetadata:
        return await self._provider_for_resource(normalized).fetch_metadata(normalized)

    async def download_video(self, normalized: NormalizedResource, work_dir: Path) -> Path:
        return await self._provider_for_resource(normalized).download_video(normalized, work_dir)

    async def download_audio(self, normalized: NormalizedResource, work_dir: Path) -> Path | None:
        return await self._provider_for_resource(normalized).download_audio(normalized, work_dir)

    async def download_image_entry(
        self,
        normalized: NormalizedResource,
        work_dir: Path,
        *,
        source_url: str,
        entry_index: int,
    ) -> Path:
        return await self._provider_for_resource(normalized).download_image_entry(
            normalized,
            work_dir,
            source_url=source_url,
            entry_index=entry_index,
        )

    async def download_images(self, normalized: NormalizedResource, work_dir: Path) -> tuple[Path, ...]:
        return await self._provider_for_resource(normalized).download_images(normalized, work_dir)

    def _provider_for_url(self, url: str) -> DownloaderProvider:
        engine_name = select_engine_name(self._platform, url)
        return self._gallery_provider if engine_name == "gallery-dl" else self._ytdlp_provider

    def _provider_for_resource(self, normalized: NormalizedResource) -> DownloaderProvider:
        return self._gallery_provider if normalized.engine_name == "gallery-dl" else self._ytdlp_provider
