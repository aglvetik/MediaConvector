from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.domain.entities.media_result import MediaMetadata
from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.enums.platform import Platform
from app.domain.errors import NormalizationError, UnsupportedUrlError
from app.domain.policies import build_cache_key
from app.infrastructure.downloaders import YtDlpClient
from app.infrastructure.logging import get_logger, log_event
from app.infrastructure.providers.tiktok.url_utils import extract_first_tiktok_url, extract_video_id, is_tiktok_host, sanitize_url


class TikTokProvider:
    platform_name = Platform.TIKTOK.value

    def __init__(self, *, downloader: YtDlpClient, request_timeout_seconds: int) -> None:
        self._downloader = downloader
        self._request_timeout_seconds = request_timeout_seconds
        self._logger = get_logger(__name__)

    def extract_first_url(self, text: str) -> str | None:
        return extract_first_tiktok_url(text)

    def can_handle(self, url: str) -> bool:
        return is_tiktok_host(url)

    async def normalize(self, url: str) -> NormalizedResource:
        if not self.can_handle(url):
            raise UnsupportedUrlError()

        original_url = url
        try:
            resolved_url = await self._resolve_short_url(url)
        except httpx.HTTPError as exc:
            raise NormalizationError("Failed to resolve TikTok short URL.", context={"url": original_url}) from exc
        resource_id = extract_video_id(resolved_url)
        canonical_url = sanitize_url(resolved_url)

        if resource_id is None:
            info = await self._downloader.probe_url(original_url)
            resource_id = str(info.get("id") or "")
            canonical_url = sanitize_url(str(info.get("webpage_url") or canonical_url))
            if not resource_id:
                raise NormalizationError("Could not extract TikTok video id.", context={"url": original_url})

        normalized_key = build_cache_key(Platform.TIKTOK, "video", resource_id)
        normalized = NormalizedResource(
            platform=Platform.TIKTOK,
            resource_type="video",
            resource_id=resource_id,
            normalized_key=normalized_key,
            original_url=original_url,
            canonical_url=canonical_url if "/video/" in canonical_url else f"https://www.tiktok.com/@_/video/{resource_id}",
        )
        log_event(self._logger, 20, "normalization_completed", normalized_key=normalized.normalized_key, canonical_url=normalized.canonical_url)
        return normalized

    async def fetch_metadata(self, normalized: NormalizedResource) -> MediaMetadata:
        return await self._downloader.fetch_metadata(normalized)

    async def download_video(self, normalized: NormalizedResource, work_dir: Path) -> Path:
        path, _ = await self._downloader.download_video(normalized, work_dir)
        return path

    async def download_with_metadata(self, normalized: NormalizedResource, work_dir: Path) -> tuple[Path, MediaMetadata]:
        return await self._downloader.download_video(normalized, work_dir)

    async def _resolve_short_url(self, url: str) -> str:
        host = (urlparse(url).hostname or "").lower()
        if host not in {"vm.tiktok.com", "vt.tiktok.com"}:
            return sanitize_url(url)
        async with httpx.AsyncClient(follow_redirects=True, timeout=self._request_timeout_seconds) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                    )
                },
            )
            response.raise_for_status()
            return sanitize_url(str(response.url))
