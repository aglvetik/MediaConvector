from __future__ import annotations

import pytest

from app.domain.entities.media_result import MediaMetadata
from app.domain.enums.platform import Platform
from app.infrastructure.providers.generic_provider import YtDlpUrlProvider


class StubDownloader:
    def __init__(self, info: dict[str, object]) -> None:
        self._info = info

    async def probe_url(self, url: str, *, extra_options: dict[str, object] | None = None) -> dict[str, object]:
        return dict(self._info)


@pytest.mark.asyncio
async def test_generic_provider_normalizes_single_video_result() -> None:
    provider = YtDlpUrlProvider(
        platform=Platform.YOUTUBE,
        downloader=StubDownloader(
            {
                "id": "abc123",
                "title": "Demo title",
                "uploader": "Demo channel",
                "webpage_url": "https://www.youtube.com/watch?v=abc123",
                "duration": 120,
                "vcodec": "avc1",
                "acodec": "mp4a.40.2",
                "ext": "mp4",
            }
        ),
        request_timeout_seconds=10,
    )

    normalized = await provider.normalize("https://youtu.be/abc123")
    metadata = await provider.fetch_metadata(normalized)

    assert normalized.resource_type == "video"
    assert normalized.resource_id == "abc123"
    assert normalized.canonical_url == "https://www.youtube.com/watch?v=abc123"
    assert normalized.normalized_key == "youtube:video:abc123"
    assert metadata == MediaMetadata(
        title="Demo title",
        duration_sec=120,
        author="Demo channel",
        description=None,
        size_bytes=None,
        has_audio=None,
    )


@pytest.mark.asyncio
async def test_generic_provider_normalizes_image_gallery_result() -> None:
    provider = YtDlpUrlProvider(
        platform=Platform.INSTAGRAM,
        downloader=StubDownloader(
            {
                "id": "gallery-1",
                "title": "Gallery",
                "uploader": "Poster",
                "webpage_url": "https://www.instagram.com/p/gallery-1/",
                "entries": [
                    {"url": "https://cdn.example/1.jpg", "ext": "jpg"},
                    {"url": "https://cdn.example/2.jpg", "ext": "jpg"},
                ],
            }
        ),
        request_timeout_seconds=10,
    )

    normalized = await provider.normalize("https://www.instagram.com/p/gallery-1/")
    metadata = await provider.fetch_metadata(normalized)

    assert normalized.resource_type == "photo_post"
    assert normalized.image_urls == ("https://cdn.example/1.jpg", "https://cdn.example/2.jpg")
    assert metadata.has_audio is False


@pytest.mark.asyncio
async def test_generic_provider_normalizes_audio_only_result() -> None:
    provider = YtDlpUrlProvider(
        platform=Platform.LIKEE,
        downloader=StubDownloader(
            {
                "id": "sound-42",
                "title": "Sound",
                "uploader": "Creator",
                "webpage_url": "https://likee.video/@user/sound/42",
                "url": "https://cdn.example/sound-42.m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "ext": "m4a",
            }
        ),
        request_timeout_seconds=10,
    )

    normalized = await provider.normalize("https://likee.video/@user/sound/42")
    metadata = await provider.fetch_metadata(normalized)

    assert normalized.resource_type == "music_only"
    assert normalized.audio_url == "https://likee.video/@user/sound/42"
    assert normalized.normalized_key == "likee:music_only:sound-42"
    assert metadata.has_audio is True
