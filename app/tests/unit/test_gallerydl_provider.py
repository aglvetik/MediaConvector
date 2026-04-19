from __future__ import annotations

import pytest

from app.domain.enums.platform import Platform
from app.infrastructure.providers.gallerydl_provider import GalleryDlUrlProvider


class StubGalleryDownloader:
    def __init__(self, entries: tuple[dict[str, object], ...]) -> None:
        self._entries = entries
        self.probe_calls: list[str] = []

    async def probe_url(self, url: str) -> tuple[dict[str, object], ...]:
        self.probe_calls.append(url)
        return self._entries


@pytest.mark.asyncio
async def test_gallery_provider_normalizes_instagram_carousel() -> None:
    provider = GalleryDlUrlProvider(
        platform=Platform.INSTAGRAM,
        downloader=StubGalleryDownloader(
            (
                {"id": "gallery-1", "title": "Carousel", "author": "Poster", "url": "https://cdn.example/1.jpg", "extension": "jpg"},
                {"id": "gallery-1", "title": "Carousel", "author": "Poster", "url": "https://cdn.example/2.jpg", "extension": "jpg"},
            )
        ),
        request_timeout_seconds=10,
    )

    normalized = await provider.normalize("https://www.instagram.com/p/gallery-1/")
    metadata = await provider.fetch_metadata(normalized)

    assert normalized.resource_type == "photo_post"
    assert normalized.engine_name == "gallery-dl"
    assert normalized.media_kind == "gallery"
    assert normalized.image_urls == ("https://cdn.example/1.jpg", "https://cdn.example/2.jpg")
    assert metadata.has_audio is False


@pytest.mark.asyncio
async def test_gallery_provider_normalizes_single_pinterest_image() -> None:
    provider = GalleryDlUrlProvider(
        platform=Platform.PINTEREST,
        downloader=StubGalleryDownloader(
            (
                {"id": "pin-1", "title": "Pin", "author": "Pinner", "url": "https://cdn.example/pin-1.png", "extension": "png"},
            )
        ),
        request_timeout_seconds=10,
    )

    normalized = await provider.normalize("https://www.pinterest.com/pin/pin-1/")

    assert normalized.resource_type == "photo_post"
    assert normalized.engine_name == "gallery-dl"
    assert normalized.media_kind == "photo"
    assert normalized.entry_count == 1
    assert normalized.image_entries[0].source_url == "https://cdn.example/pin-1.png"
