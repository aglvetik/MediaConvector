from __future__ import annotations

import logging
from pathlib import Path

import httpx

from app.infrastructure.logging import get_logger, log_event


class HttpMusicMetadataProvider:
    provider_name = "http_metadata"

    def __init__(self, *, timeout_seconds: int) -> None:
        self._timeout_seconds = timeout_seconds
        self._logger = get_logger(__name__)

    async def download_thumbnail(self, thumbnail_url: str, work_dir: Path, *, fallback_stem: str) -> Path | None:
        output_path = work_dir / f"{fallback_stem}-thumb"
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds, follow_redirects=True) as client:
                response = await client.get(thumbnail_url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            log_event(
                self._logger,
                logging.WARNING,
                "music_thumbnail_download_failed",
                thumbnail_url=thumbnail_url,
                error=str(exc),
            )
            return None

        suffix = _guess_image_suffix(response.headers.get("content-type"), thumbnail_url)
        target_path = output_path.with_suffix(suffix)
        target_path.write_bytes(response.content)
        if target_path.stat().st_size == 0:
            return None
        return target_path


def _guess_image_suffix(content_type: str | None, thumbnail_url: str) -> str:
    lowered_content_type = (content_type or "").lower()
    if "png" in lowered_content_type or thumbnail_url.lower().endswith(".png"):
        return ".png"
    if "webp" in lowered_content_type or thumbnail_url.lower().endswith(".webp"):
        return ".webp"
    return ".jpg"
