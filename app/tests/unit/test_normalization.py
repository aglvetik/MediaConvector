from app.infrastructure.providers.tiktok.provider import TikTokProvider


class DummyDownloader:
    async def fetch_metadata(self, normalized):  # pragma: no cover - not used in these tests
        raise AssertionError("fetch_metadata should not be called")

    async def probe_url(self, url: str) -> dict[str, str]:
        return {"id": "445566", "webpage_url": "https://www.tiktok.com/@name/video/445566"}


async def test_tiktok_normalization_standard_url() -> None:
    provider = TikTokProvider(downloader=DummyDownloader(), request_timeout_seconds=5)
    normalized = await provider.normalize("https://www.tiktok.com/@user/video/1122334455?lang=ru")
    assert normalized.resource_id == "1122334455"
    assert normalized.normalized_key == "tiktok:video:1122334455"
    assert normalized.canonical_url == "https://www.tiktok.com/@user/video/1122334455"


async def test_tiktok_normalization_uses_probe_fallback(monkeypatch) -> None:
    provider = TikTokProvider(downloader=DummyDownloader(), request_timeout_seconds=5)

    async def fake_resolve(url: str) -> str:
        return "https://www.tiktok.com/share/video/?item_id=445566"

    monkeypatch.setattr(provider, "_resolve_short_url", fake_resolve)
    normalized = await provider.normalize("https://vm.tiktok.com/ZM123456/")
    assert normalized.resource_id == "445566"
    assert normalized.normalized_key == "tiktok:video:445566"
