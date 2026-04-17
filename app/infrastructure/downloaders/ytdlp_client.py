from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yt_dlp

from app.domain.entities.media_result import MediaMetadata
from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.errors import DownloadError, DownloadUnavailableError
from app.infrastructure.logging import get_logger, log_event


class YtDlpClient:
    def __init__(self, *, binary_path: str, timeout_seconds: int, semaphore: asyncio.Semaphore) -> None:
        self._binary_path = binary_path
        self._timeout_seconds = timeout_seconds
        self._semaphore = semaphore
        self._logger = get_logger(__name__)

    async def fetch_metadata(self, normalized: NormalizedResource) -> MediaMetadata:
        async with self._semaphore:
            log_event(
                self._logger,
                20,
                "download_metadata_started",
                normalized_key=normalized.normalized_key,
                canonical_url=normalized.canonical_url,
            )
            try:
                info = await asyncio.wait_for(
                    asyncio.to_thread(self._extract_info, normalized.canonical_url, False, None),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                raise DownloadError("yt-dlp metadata extraction timed out.", context={"normalized_key": normalized.normalized_key}) from exc
            return self._build_metadata(info)

    async def probe_url(self, url: str) -> dict[str, Any]:
        async with self._semaphore:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._extract_info, url, False, None),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                raise DownloadError("yt-dlp URL probe timed out.") from exc

    async def download_video(self, normalized: NormalizedResource, work_dir: Path) -> tuple[Path, MediaMetadata]:
        async with self._semaphore:
            log_event(
                self._logger,
                20,
                "download_started",
                normalized_key=normalized.normalized_key,
                canonical_url=normalized.canonical_url,
            )
            try:
                info = await asyncio.wait_for(
                    asyncio.to_thread(self._extract_info, normalized.canonical_url, True, work_dir),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                raise DownloadError("yt-dlp download timed out.", context={"normalized_key": normalized.normalized_key}) from exc

            downloaded_path = self._resolve_downloaded_path(work_dir, info)
            log_event(
                self._logger,
                20,
                "download_finished",
                normalized_key=normalized.normalized_key,
                file_path=str(downloaded_path),
            )
            return downloaded_path, self._build_metadata(info)

    def _extract_info(self, url: str, download: bool, work_dir: Path | None) -> dict[str, Any]:
        outtmpl = None if work_dir is None else str(work_dir / "%(id)s.%(ext)s")
        options: dict[str, Any] = {
            "paths": {"home": str(work_dir)} if work_dir is not None else None,
            "outtmpl": outtmpl,
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "socket_timeout": self._timeout_seconds,
            "extractor_retries": 3,
            "cachedir": False,
        }
        options = {key: value for key, value in options.items() if value is not None}
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=download)
        except yt_dlp.utils.DownloadError as exc:
            message = str(exc)
            lower = message.lower()
            if any(marker in lower for marker in ("video unavailable", "status code 404", "unable to extract url")):
                raise DownloadUnavailableError(message) from exc
            if any(marker in lower for marker in ("private", "login required", "sign in", "not available")):
                raise DownloadError(message, temporary=False) from exc
            if any(marker in lower for marker in ("timed out", "429", "too many requests", "temporary")):
                raise DownloadError(message, temporary=True) from exc
            raise DownloadError(message, temporary=True) from exc
        return info

    @staticmethod
    def _resolve_downloaded_path(work_dir: Path, info: dict[str, Any]) -> Path:
        requested_downloads = info.get("requested_downloads") or []
        for item in requested_downloads:
            filepath = item.get("filepath")
            if filepath:
                return Path(filepath)
        filepath = info.get("_filename") or info.get("filepath")
        if filepath:
            return Path(filepath)
        candidates = sorted(work_dir.glob("*"))
        if not candidates:
            raise DownloadError("yt-dlp finished without producing a file.")
        return candidates[0]

    @staticmethod
    def _build_metadata(info: dict[str, Any]) -> MediaMetadata:
        return MediaMetadata(
            title=info.get("title"),
            duration_sec=info.get("duration"),
            author=info.get("uploader") or info.get("channel"),
            description=info.get("description"),
            size_bytes=info.get("filesize") or info.get("filesize_approx"),
            has_audio=info.get("acodec") not in {None, "none"},
        )
