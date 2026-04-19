from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.entities.media_result import MediaMetadata
from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.enums.platform import Platform
from app.infrastructure.providers.engine_routing import select_engine_name
from app.infrastructure.providers.routed_provider import RoutedUrlProvider


class StubProvider:
    def __init__(self, normalized: NormalizedResource) -> None:
        self._normalized = normalized
        self.normalize_calls: list[str] = []

    def extract_first_url(self, text: str) -> str | None:  # pragma: no cover - not needed here
        return None

    def can_handle(self, url: str) -> bool:  # pragma: no cover - not needed here
        return True

    async def normalize(self, url: str) -> NormalizedResource:
        self.normalize_calls.append(url)
        return self._normalized

    async def fetch_metadata(self, normalized: NormalizedResource) -> MediaMetadata:  # pragma: no cover - not needed here
        return MediaMetadata(title=None, duration_sec=None, author=None, description=None, size_bytes=None, has_audio=None)

    async def download_video(self, normalized: NormalizedResource, work_dir: Path) -> Path:  # pragma: no cover - not needed here
        raise AssertionError("download_video should not be called")

    async def download_audio(self, normalized: NormalizedResource, work_dir: Path) -> Path | None:  # pragma: no cover - not needed here
        raise AssertionError("download_audio should not be called")

    async def download_image_entry(  # pragma: no cover - not needed here
        self,
        normalized: NormalizedResource,
        work_dir: Path,
        *,
        source_url: str,
        entry_index: int,
    ) -> Path:
        raise AssertionError("download_image_entry should not be called")

    async def download_images(self, normalized: NormalizedResource, work_dir: Path) -> tuple[Path, ...]:  # pragma: no cover - not needed here
        raise AssertionError("download_images should not be called")


def test_select_engine_name_routes_visual_first_sources_to_gallery_dl() -> None:
    assert select_engine_name(Platform.TIKTOK, "https://www.tiktok.com/@user/photo/123") == "gallery-dl"
    assert select_engine_name(Platform.INSTAGRAM, "https://www.instagram.com/p/demo/") == "gallery-dl"
    assert select_engine_name(Platform.PINTEREST, "https://www.pinterest.com/pin/123/") == "gallery-dl"


def test_select_engine_name_routes_video_first_sources_to_ytdlp() -> None:
    assert select_engine_name(Platform.TIKTOK, "https://www.tiktok.com/@user/video/123") == "yt-dlp"
    assert select_engine_name(Platform.YOUTUBE, "https://youtu.be/demo") == "yt-dlp"
    assert select_engine_name(Platform.INSTAGRAM, "https://www.instagram.com/reel/demo/") == "yt-dlp"


@pytest.mark.asyncio
async def test_routed_provider_uses_gallery_provider_for_instagram_carousel() -> None:
    ytdlp_provider = StubProvider(
        NormalizedResource(
            platform=Platform.INSTAGRAM,
            resource_type="video",
            resource_id="reel",
            normalized_key="instagram:video:reel",
            original_url="https://www.instagram.com/reel/reel/",
            canonical_url="https://www.instagram.com/reel/reel/",
            engine_name="yt-dlp",
        )
    )
    gallery_provider = StubProvider(
        NormalizedResource(
            platform=Platform.INSTAGRAM,
            resource_type="photo_post",
            resource_id="gallery",
            normalized_key="instagram:photo_post:gallery",
            original_url="https://www.instagram.com/p/gallery/",
            canonical_url="https://www.instagram.com/p/gallery/",
            engine_name="gallery-dl",
            media_kind="gallery",
        )
    )
    provider = RoutedUrlProvider(
        platform=Platform.INSTAGRAM,
        ytdlp_provider=ytdlp_provider,
        gallery_provider=gallery_provider,
    )

    normalized = await provider.normalize("https://www.instagram.com/p/gallery/")

    assert normalized.engine_name == "gallery-dl"
    assert gallery_provider.normalize_calls == ["https://www.instagram.com/p/gallery/"]
    assert ytdlp_provider.normalize_calls == []


@pytest.mark.asyncio
async def test_routed_provider_uses_ytdlp_for_youtube_video() -> None:
    ytdlp_provider = StubProvider(
        NormalizedResource(
            platform=Platform.YOUTUBE,
            resource_type="video",
            resource_id="abc123",
            normalized_key="youtube:video:abc123",
            original_url="https://youtu.be/abc123",
            canonical_url="https://youtu.be/abc123",
            engine_name="yt-dlp",
        )
    )
    gallery_provider = StubProvider(
        NormalizedResource(
            platform=Platform.YOUTUBE,
            resource_type="photo_post",
            resource_id="abc123",
            normalized_key="youtube:photo_post:abc123",
            original_url="https://youtu.be/abc123",
            canonical_url="https://youtu.be/abc123",
            engine_name="gallery-dl",
            media_kind="photo",
        )
    )
    provider = RoutedUrlProvider(
        platform=Platform.YOUTUBE,
        ytdlp_provider=ytdlp_provider,
        gallery_provider=gallery_provider,
    )

    normalized = await provider.normalize("https://youtu.be/abc123")

    assert normalized.engine_name == "yt-dlp"
    assert ytdlp_provider.normalize_calls == ["https://youtu.be/abc123"]
    assert gallery_provider.normalize_calls == []
