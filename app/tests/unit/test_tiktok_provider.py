from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.enums.platform import Platform
from app.infrastructure.providers.tiktok.provider import TikTokProvider


class StubDownloader:
    def __init__(self, info: dict[str, object]) -> None:
        self._info = info

    async def probe_url(self, url: str, *, extra_options: dict[str, object] | None = None) -> dict[str, object]:
        return dict(self._info)


@pytest.mark.asyncio
async def test_tiktok_photo_normalization_upgrades_muscdn_http_to_https(monkeypatch) -> None:
    provider = TikTokProvider(
        downloader=StubDownloader(
            {
                "id": "12345",
                "entries": [
                    {"url": "http://p16.muscdn.com/img/one~noop.webp"},
                    {"display_image": "http://p16.muscdn.com/img/two~noop.webp"},
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
        "https://p16.muscdn.com/img/one~noop.webp",
        "https://p16.muscdn.com/img/two~noop.webp",
    )
    assert tuple(entry.source_url for entry in normalized.image_entries) == normalized.image_urls


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
