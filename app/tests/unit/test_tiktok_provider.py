from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.enums.platform import Platform
from app.domain.errors import DownloadError
from app.infrastructure.providers.tiktok.provider import TikTokProvider


class StubDownloader:
    def __init__(self, info: dict[str, object]) -> None:
        self._info = info
        self.probe_urls: list[str] = []
        self.download_audio_urls: list[str] = []
        self.download_video_urls: list[str] = []
        self.fetch_metadata_urls: list[str] = []

    async def probe_url(self, url: str, *, extra_options: dict[str, object] | None = None) -> dict[str, object]:
        self.probe_urls.append(url)
        return dict(self._info)

    async def fetch_metadata(self, normalized) -> object:
        self.fetch_metadata_urls.append(normalized.canonical_url)
        from app.domain.entities.media_result import MediaMetadata

        return MediaMetadata(
            title=self._info.get("title"),
            duration_sec=self._info.get("duration"),
            author=self._info.get("uploader"),
            description=None,
            size_bytes=None,
            has_audio=True,
        )

    async def download_audio(self, url: str, work_dir: Path, *, normalized_key: str, extra_options: dict[str, object] | None = None):
        self.download_audio_urls.append(url)
        target = work_dir / "audio.m4a"
        target.write_bytes(b"audio")
        from app.domain.entities.media_result import MediaMetadata

        return target, MediaMetadata(
            title=self._info.get("title"),
            duration_sec=self._info.get("duration"),
            author=self._info.get("uploader"),
            description=None,
            size_bytes=None,
            has_audio=True,
        )

    async def download_video(self, normalized, work_dir: Path):
        self.download_video_urls.append(normalized.canonical_url)
        target = work_dir / "video.mp4"
        target.write_bytes(b"video")
        from app.domain.entities.media_result import MediaMetadata

        return target, MediaMetadata(
            title=self._info.get("title"),
            duration_sec=self._info.get("duration"),
            author=self._info.get("uploader"),
            description=None,
            size_bytes=None,
            has_audio=True,
        )


class StubGalleryDownloader:
    def __init__(self, entries: tuple[dict[str, object], ...]) -> None:
        self._entries = entries
        self.probe_urls: list[str] = []

    async def probe_url(self, url: str) -> tuple[dict[str, object], ...]:
        self.probe_urls.append(url)
        return self._entries


@pytest.mark.asyncio
async def test_tiktok_photo_normalization_prefers_structured_image_url_list_over_raw_entry_url(monkeypatch) -> None:
    provider = TikTokProvider(
        downloader=StubDownloader(
            {
                "id": "12345",
                "entries": [
                    {
                        "url": "https://p16.muscdn.com/img/one~noop.webp",
                        "image_url": {
                            "url_list": [
                                "https://p16-sign-va.tiktokcdn.com/obj/tos-maliva-p-0068/one.webp",
                                "https://p16.muscdn.com/img/one~noop.webp",
                            ]
                        },
                    },
                    {
                        "url": "https://p16.muscdn.com/img/two~noop.webp",
                        "imageURL": {
                            "urlList": [
                                "https://p16-sign-va.tiktokcdn.com/obj/tos-maliva-p-0068/two.webp",
                            ]
                        },
                    },
                ],
            }
        ),
        request_timeout_seconds=10,
    )

    async def fake_resolve_short_url(url: str) -> str:
        return url

    async def fake_load_web_state(url: str) -> dict[str, object]:
        return {}

    monkeypatch.setattr(provider, "_resolve_short_url", fake_resolve_short_url)
    monkeypatch.setattr(provider, "_load_web_state", fake_load_web_state)

    normalized = await provider.normalize("https://www.tiktok.com/@user/photo/12345")

    assert normalized.platform == Platform.TIKTOK
    assert normalized.resource_type == "photo_post"
    assert normalized.media_kind == "gallery"
    assert normalized.image_urls == (
        "https://p16-sign-va.tiktokcdn.com/obj/tos-maliva-p-0068/one.webp",
        "https://p16-sign-va.tiktokcdn.com/obj/tos-maliva-p-0068/two.webp",
    )
    assert tuple(entry.source_url for entry in normalized.image_entries) == normalized.image_urls
    assert all("muscdn.com" not in image_url for image_url in normalized.image_urls)


@pytest.mark.asyncio
async def test_tiktok_photo_normalization_uses_structured_web_state_images_when_entries_only_have_raw_urls(monkeypatch) -> None:
    provider = TikTokProvider(
        downloader=StubDownloader(
            {
                "id": "54321",
                "entries": [
                    {"url": "https://p16.muscdn.com/img/one~noop.webp"},
                    {"url": "https://p16.muscdn.com/img/two~noop.webp"},
                ],
            }
        ),
        request_timeout_seconds=10,
    )

    async def fake_resolve_short_url(url: str) -> str:
        return url

    async def fake_load_web_state(url: str) -> dict[str, object]:
        return {
            "ItemModule": {
                "54321": {
                    "imagePost": {
                        "images": [
                            {
                                "imageURL": {
                                    "urlList": [
                                        "https://p16-sign-va.tiktokcdn.com/obj/tos-maliva-p-0068/three.webp",
                                        "https://p16.muscdn.com/img/one~noop.webp",
                                    ]
                                }
                            },
                            {
                                "imageURL": {
                                    "urlList": [
                                        "https://p16-sign-va.tiktokcdn.com/obj/tos-maliva-p-0068/four.webp",
                                    ]
                                }
                            },
                        ]
                    }
                }
            }
        }

    monkeypatch.setattr(provider, "_resolve_short_url", fake_resolve_short_url)
    monkeypatch.setattr(provider, "_load_web_state", fake_load_web_state)

    normalized = await provider.normalize("https://www.tiktok.com/@user/photo/54321")

    assert normalized.image_urls == (
        "https://p16-sign-va.tiktokcdn.com/obj/tos-maliva-p-0068/three.webp",
        "https://p16-sign-va.tiktokcdn.com/obj/tos-maliva-p-0068/four.webp",
    )
    assert all("muscdn.com" not in image_url for image_url in normalized.image_urls)


@pytest.mark.asyncio
async def test_tiktok_image_download_uses_tiktok_headers_and_https(monkeypatch, tmp_path: Path) -> None:
    provider = TikTokProvider(
        downloader=StubDownloader({"id": "12345"}),
        request_timeout_seconds=10,
    )
    captured: dict[str, object] = {}

    class FakeResponse:
        def __init__(self) -> None:
            self.content = b"image-bytes"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str, *, headers: dict[str, str] | None = None) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("app.infrastructure.providers.tiktok.provider.httpx.AsyncClient", FakeClient)

    await provider._download_binary(  # type: ignore[attr-defined]
        "https://p16.muscdn.com/img/one~noop.webp",
        tmp_path / "image.webp",
        original_url="http://p16.muscdn.com/img/one~noop.webp",
        headers=provider._asset_headers("https://p16.muscdn.com/img/one~noop.webp"),  # type: ignore[attr-defined]
        allow_https_retry=True,
    )

    assert captured["url"] == "https://p16.muscdn.com/img/one~noop.webp"
    headers = captured["headers"]
    assert headers is not None
    assert headers["Referer"] == "https://www.tiktok.com/"
    assert headers["Accept"] == "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
    assert headers["Accept-Language"] == "en-US,en;q=0.9"
    assert "Mozilla/5.0" in headers["User-Agent"]


@pytest.mark.asyncio
async def test_vm_tiktok_short_link_normalizes_to_canonical_video_url(monkeypatch) -> None:
    downloader = StubDownloader({"id": "7600774477374393617", "formats": [{"url": "https://cdn.example/video.mp4", "vcodec": "h264"}]})
    provider = TikTokProvider(downloader=downloader, request_timeout_seconds=10)

    expanded_url = "https://www.tiktok.com/@username/video/7600774477374393617?_r=1&_t=abcdef"

    async def fake_resolve_short_url(url: str) -> str:
        return expanded_url

    async def fake_load_web_state(url: str) -> dict[str, object]:
        return {}

    monkeypatch.setattr(provider, "_resolve_short_url", fake_resolve_short_url)
    monkeypatch.setattr(provider, "_load_web_state", fake_load_web_state)

    normalized = await provider.normalize("https://vm.tiktok.com/ZM12345/")

    assert normalized.resource_type == "video"
    assert normalized.resource_id == "7600774477374393617"
    assert normalized.canonical_url == "https://www.tiktok.com/@username/video/7600774477374393617"
    assert normalized.normalized_key == "tiktok:video:7600774477374393617"
    assert downloader.probe_urls == ["https://www.tiktok.com/@username/video/7600774477374393617"]
    assert normalized.engine_name == "yt-dlp"


@pytest.mark.asyncio
async def test_vm_tiktok_short_link_normalizes_to_canonical_photo_url(monkeypatch) -> None:
    downloader = StubDownloader(
        {
            "id": "7600774477374393618",
            "entries": [
                {"image_url": {"url_list": ["https://p16-sign-va.tiktokcdn.com/obj/tos-maliva-p-0068/one.webp"]}},
                {"image_url": {"url_list": ["https://p16-sign-va.tiktokcdn.com/obj/tos-maliva-p-0068/two.webp"]}},
            ],
        }
    )
    provider = TikTokProvider(downloader=downloader, request_timeout_seconds=10)

    expanded_url = "https://www.tiktok.com/@username/photo/7600774477374393618?_r=1&_t=abcdef"

    async def fake_resolve_short_url(url: str) -> str:
        return expanded_url

    async def fake_load_web_state(url: str) -> dict[str, object]:
        return {}

    monkeypatch.setattr(provider, "_resolve_short_url", fake_resolve_short_url)
    monkeypatch.setattr(provider, "_load_web_state", fake_load_web_state)

    normalized = await provider.normalize("https://vm.tiktok.com/ZM54321/")

    assert normalized.resource_type == "photo_post"
    assert normalized.resource_id == "7600774477374393618"
    assert normalized.canonical_url == "https://www.tiktok.com/@username/photo/7600774477374393618"
    assert normalized.normalized_key == "tiktok:photo_post:7600774477374393618"
    assert downloader.probe_urls == ["https://www.tiktok.com/@username/photo/7600774477374393618"]


@pytest.mark.asyncio
async def test_tiktok_photo_normalization_prefers_gallery_dl_engine_when_configured(monkeypatch) -> None:
    downloader = StubDownloader(
        {
            "id": "7600774477374393618",
            "entries": [
                {"url": "https://cdn.example/fallback-1.webp"},
                {"url": "https://cdn.example/fallback-2.webp"},
            ],
        }
    )
    gallery_downloader = StubGalleryDownloader(
        (
            {"id": "7600774477374393618", "title": "Photo post", "author": "Poster", "url": "https://gallery.example/1.jpg", "extension": "jpg"},
            {"id": "7600774477374393618", "title": "Photo post", "author": "Poster", "url": "https://gallery.example/2.jpg", "extension": "jpg"},
        )
    )
    provider = TikTokProvider(
        downloader=downloader,
        request_timeout_seconds=10,
        gallery_downloader=gallery_downloader,
    )

    async def fake_resolve_short_url(url: str) -> str:
        return url

    async def fake_load_web_state(url: str) -> dict[str, object]:
        return {}

    monkeypatch.setattr(provider, "_resolve_short_url", fake_resolve_short_url)
    monkeypatch.setattr(provider, "_load_web_state", fake_load_web_state)

    normalized = await provider.normalize("https://www.tiktok.com/@username/photo/7600774477374393618")

    assert normalized.engine_name == "gallery-dl"
    assert normalized.image_urls == ("https://gallery.example/1.jpg", "https://gallery.example/2.jpg")
    assert gallery_downloader.probe_urls == ["https://www.tiktok.com/@username/photo/7600774477374393618"]


@pytest.mark.asyncio
async def test_tiktok_music_url_normalization_skips_gallery_probe(monkeypatch) -> None:
    downloader = StubDownloader(
        {
            "id": "777777",
            "title": "Original sound",
            "uploader": "Creator",
            "formats": [{"url": "https://v16.tiktokcdn.com/audio.m4a", "vcodec": "none", "acodec": "aac"}],
        }
    )
    gallery_downloader = StubGalleryDownloader(())
    provider = TikTokProvider(
        downloader=downloader,
        request_timeout_seconds=10,
        gallery_downloader=gallery_downloader,
    )

    async def fake_resolve_short_url(url: str) -> str:
        return url

    async def fake_load_web_state(url: str) -> dict[str, object]:
        return {
            "musicInfo": {
                "originalVideo": {
                    "id": "1234567890123456789",
                    "authorName": "creator",
                    "musicId": "777777",
                }
            }
        }

    monkeypatch.setattr(provider, "_resolve_short_url", fake_resolve_short_url)
    monkeypatch.setattr(provider, "_load_web_state", fake_load_web_state)

    normalized = await provider.normalize("https://www.tiktok.com/music/original-sound-777777")

    assert normalized.resource_type == "music_only"
    assert normalized.engine_name == "yt-dlp"
    assert normalized.normalized_key == "tiktok:music_only:777777"
    assert normalized.source_video_url == "https://www.tiktok.com/@creator/video/1234567890123456789"
    assert normalized.source_video_id == "1234567890123456789"
    assert gallery_downloader.probe_urls == []
    assert downloader.probe_urls == []


@pytest.mark.asyncio
async def test_tiktok_music_url_prefers_original_source_video_download(monkeypatch, tmp_path: Path) -> None:
    downloader = StubDownloader(
        {
            "id": "888888",
            "title": "Original sound",
            "uploader": "Creator",
            "formats": [{"url": "https://v16.tiktokcdn.com/audio.m4a", "vcodec": "none", "acodec": "aac"}],
        }
    )
    provider = TikTokProvider(
        downloader=downloader,
        request_timeout_seconds=10,
        gallery_downloader=StubGalleryDownloader(()),
    )

    async def fake_resolve_short_url(url: str) -> str:
        return url

    async def fake_load_web_state(url: str) -> dict[str, object]:
        return {
            "musicInfo": {
                "originalVideo": {
                    "id": "998877665544332211",
                    "authorName": "creator",
                    "musicId": "888888",
                }
            }
        }

    monkeypatch.setattr(provider, "_resolve_short_url", fake_resolve_short_url)
    monkeypatch.setattr(provider, "_load_web_state", fake_load_web_state)

    normalized = await provider.normalize("https://www.tiktok.com/music/original-sound-888888")
    video_path = await provider.download_video(normalized, tmp_path)

    assert video_path is not None
    assert video_path.exists()
    assert video_path.suffix == ".mp4"
    assert downloader.download_video_urls == ["https://www.tiktok.com/@creator/video/998877665544332211"]
    assert downloader.download_audio_urls == []


@pytest.mark.asyncio
async def test_tiktok_music_url_blocks_direct_audio_branch_when_source_video_is_resolved(monkeypatch, tmp_path: Path) -> None:
    downloader = StubDownloader({"id": "888889", "title": "Original sound", "uploader": "Creator"})
    provider = TikTokProvider(
        downloader=downloader,
        request_timeout_seconds=10,
        gallery_downloader=StubGalleryDownloader(()),
    )

    async def fake_resolve_short_url(url: str) -> str:
        return url

    async def fake_load_web_state(url: str) -> dict[str, object]:
        return {
            "musicInfo": {
                "originalVideo": {
                    "id": "998877665544332212",
                    "authorName": "creator",
                    "musicId": "888889",
                }
            }
        }

    monkeypatch.setattr(provider, "_resolve_short_url", fake_resolve_short_url)
    monkeypatch.setattr(provider, "_load_web_state", fake_load_web_state)

    normalized = await provider.normalize("https://www.tiktok.com/music/original-sound-888889")

    with pytest.raises(DownloadError):
        await provider.download_audio(normalized, tmp_path)

    assert downloader.download_audio_urls == []


@pytest.mark.asyncio
async def test_tiktok_music_url_prefers_original_source_over_related_candidate(monkeypatch) -> None:
    downloader = StubDownloader({"id": "999999", "title": "Sound", "uploader": "Creator"})
    provider = TikTokProvider(downloader=downloader, request_timeout_seconds=10)

    async def fake_resolve_short_url(url: str) -> str:
        return url

    async def fake_load_web_state(url: str) -> dict[str, object]:
        return {
            "musicFeed": {
                "related": [
                    {
                        "itemId": "1111111111111111111",
                        "authorName": "related_author",
                        "musicId": "999999",
                    }
                ],
                "originalVideo": {
                    "itemId": "2222222222222222222",
                    "authorName": "source_author",
                    "musicId": "999999",
                },
            }
        }

    monkeypatch.setattr(provider, "_resolve_short_url", fake_resolve_short_url)
    monkeypatch.setattr(provider, "_load_web_state", fake_load_web_state)

    normalized = await provider.normalize("https://www.tiktok.com/music/original-sound-999999")

    assert normalized.source_video_url == "https://www.tiktok.com/@source_author/video/2222222222222222222"
    assert normalized.source_resolution_strategy == "original_source_video"


@pytest.mark.asyncio
async def test_tiktok_music_url_resolves_original_source_from_item_info_structure(monkeypatch) -> None:
    downloader = StubDownloader({"id": "112233", "title": "Sound", "uploader": "Creator"})
    provider = TikTokProvider(downloader=downloader, request_timeout_seconds=10)

    async def fake_resolve_short_url(url: str) -> str:
        return url

    async def fake_load_web_state(url: str) -> dict[str, object]:
        return {
            "itemInfo": {
                "itemStruct": {
                    "music": {"id": "112233"},
                    "anchorOriginalItem": {
                        "aweme_id": "3333333333333333333",
                        "author": {"uniqueId": "anchor_author"},
                    },
                }
            }
        }

    monkeypatch.setattr(provider, "_resolve_short_url", fake_resolve_short_url)
    monkeypatch.setattr(provider, "_load_web_state", fake_load_web_state)

    normalized = await provider.normalize("https://www.tiktok.com/music/original-sound-112233")

    assert normalized.source_video_url == "https://www.tiktok.com/@anchor_author/video/3333333333333333333"
    assert normalized.source_resolution_strategy == "original_source_video"


@pytest.mark.asyncio
async def test_tiktok_music_url_falls_back_to_earliest_published_video(monkeypatch) -> None:
    downloader = StubDownloader({"id": "445566", "title": "Sound", "uploader": "Creator"})
    provider = TikTokProvider(downloader=downloader, request_timeout_seconds=10)

    async def fake_resolve_short_url(url: str) -> str:
        return url

    async def fake_load_web_state(url: str) -> dict[str, object]:
        return {
            "musicFeed": {
                "itemList": [
                    {
                        "itemId": "7777777777777777771",
                        "authorName": "late_author",
                        "musicId": "445566",
                        "createTime": 200,
                    },
                    {
                        "itemId": "7777777777777777770",
                        "authorName": "early_author",
                        "musicId": "445566",
                        "createTime": 100,
                    },
                ]
            }
        }

    monkeypatch.setattr(provider, "_resolve_short_url", fake_resolve_short_url)
    monkeypatch.setattr(provider, "_load_web_state", fake_load_web_state)

    normalized = await provider.normalize("https://www.tiktok.com/music/original-sound-445566")

    assert normalized.source_video_url == "https://www.tiktok.com/@early_author/video/7777777777777777770"
    assert normalized.source_resolution_strategy == "earliest_sound_video"


@pytest.mark.asyncio
async def test_tiktok_music_url_uses_direct_audio_last_resort_only_when_source_resolution_fails(monkeypatch, tmp_path: Path) -> None:
    downloader = StubDownloader(
        {
            "id": "123123",
            "title": "Fallback sound",
            "uploader": "Creator",
            "formats": [{"url": "https://v16.tiktokcdn.com/audio.m4a", "vcodec": "none", "acodec": "aac"}],
        }
    )
    provider = TikTokProvider(downloader=downloader, request_timeout_seconds=10)

    async def fake_resolve_short_url(url: str) -> str:
        return url

    async def fake_load_web_state(url: str) -> dict[str, object]:
        return {}

    monkeypatch.setattr(provider, "_resolve_short_url", fake_resolve_short_url)
    monkeypatch.setattr(provider, "_load_web_state", fake_load_web_state)

    normalized = await provider.normalize("https://www.tiktok.com/music/original-sound-123123")
    audio_path = await provider.download_audio(normalized, tmp_path)

    assert normalized.source_video_url is None
    assert audio_path is not None
    assert audio_path.suffix == ".m4a"
    assert downloader.download_audio_urls == ["https://www.tiktok.com/music/original-sound-123123"]


@pytest.mark.asyncio
async def test_tiktok_music_resolution_logs_diagnostics_when_no_source_video_is_found(monkeypatch) -> None:
    downloader = StubDownloader(
        {
            "id": "123124",
            "title": "Fallback sound",
            "uploader": "Creator",
            "formats": [{"url": "https://v16.tiktokcdn.com/audio.m4a", "vcodec": "none", "acodec": "aac"}],
        }
    )
    provider = TikTokProvider(downloader=downloader, request_timeout_seconds=10)
    events: list[tuple[str, dict[str, object]]] = []

    async def fake_resolve_short_url(url: str) -> str:
        return url

    async def fake_load_web_state(url: str) -> dict[str, object]:
        return {"musicDetail": {"title": "Only audio metadata"}}

    def fake_log_event(logger, level, event_name, **fields) -> None:
        del logger, level
        events.append((event_name, fields))

    monkeypatch.setattr(provider, "_resolve_short_url", fake_resolve_short_url)
    monkeypatch.setattr(provider, "_load_web_state", fake_load_web_state)
    monkeypatch.setattr("app.infrastructure.providers.tiktok.provider.log_event", fake_log_event)

    normalized = await provider.normalize("https://www.tiktok.com/music/original-sound-123124")

    assert normalized.source_video_url is None
    event_names = [event_name for event_name, _ in events]
    assert "tiktok_music_source_resolution_diagnostics" in event_names
    assert "tiktok_music_source_video_resolution_failed" in event_names
    assert "tiktok_music_earliest_video_resolution_failed" in event_names
    diagnostics = [fields for event_name, fields in events if event_name == "tiktok_music_source_resolution_diagnostics"][0]
    assert "musicDetail" in diagnostics["web_state_top_level_keys"]
    assert diagnostics["candidate_source_video_urls"] == []


@pytest.mark.asyncio
async def test_canonical_tiktok_photo_url_with_query_params_normalizes_cleanly(monkeypatch) -> None:
    downloader = StubDownloader(
        {
            "id": "7600774477374393618",
            "entries": [
                {"image_url": {"url_list": ["https://p16-sign-va.tiktokcdn.com/obj/tos-maliva-p-0068/one.webp"]}},
            ],
        }
    )
    provider = TikTokProvider(downloader=downloader, request_timeout_seconds=10)

    async def fake_resolve_short_url(url: str) -> str:
        return url

    async def fake_load_web_state(url: str) -> dict[str, object]:
        return {}

    monkeypatch.setattr(provider, "_resolve_short_url", fake_resolve_short_url)
    monkeypatch.setattr(provider, "_load_web_state", fake_load_web_state)

    normalized = await provider.normalize("https://www.tiktok.com/@username/photo/7600774477374393618?_r=1&_t=abcdef&share_app_id=123")

    assert normalized.resource_type == "photo_post"
    assert normalized.canonical_url == "https://www.tiktok.com/@username/photo/7600774477374393618"
    assert normalized.normalized_key == "tiktok:photo_post:7600774477374393618"
    assert downloader.probe_urls == ["https://www.tiktok.com/@username/photo/7600774477374393618"]


@pytest.mark.asyncio
async def test_canonical_tiktok_video_url_with_query_params_normalizes_cleanly(monkeypatch) -> None:
    downloader = StubDownloader({"id": "7600774477374393617", "formats": [{"url": "https://cdn.example/video.mp4", "vcodec": "h264"}]})
    provider = TikTokProvider(downloader=downloader, request_timeout_seconds=10)

    async def fake_resolve_short_url(url: str) -> str:
        return url

    async def fake_load_web_state(url: str) -> dict[str, object]:
        return {}

    monkeypatch.setattr(provider, "_resolve_short_url", fake_resolve_short_url)
    monkeypatch.setattr(provider, "_load_web_state", fake_load_web_state)

    normalized = await provider.normalize("https://www.tiktok.com/@username/video/7600774477374393617?_r=1&_t=abcdef&share_app_id=123")

    assert normalized.resource_type == "video"
    assert normalized.canonical_url == "https://www.tiktok.com/@username/video/7600774477374393617"
    assert normalized.normalized_key == "tiktok:video:7600774477374393617"
    assert downloader.probe_urls == ["https://www.tiktok.com/@username/video/7600774477374393617"]
