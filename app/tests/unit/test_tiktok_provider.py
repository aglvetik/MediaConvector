from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.enums.platform import Platform
from app.infrastructure.providers.tiktok.provider import TikTokProvider


class StubDownloader:
    def __init__(self, info: dict[str, object]) -> None:
        self._info = info
        self.probe_urls: list[str] = []

    async def probe_url(self, url: str, *, extra_options: dict[str, object] | None = None) -> dict[str, object]:
        self.probe_urls.append(url)
        return dict(self._info)


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
