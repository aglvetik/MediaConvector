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
    def __init__(
        self,
        *,
        binary_path: str,
        timeout_seconds: int,
        semaphore: asyncio.Semaphore,
        cookies_file: Path | None = None,
    ) -> None:
        self._binary_path = binary_path
        self._timeout_seconds = timeout_seconds
        self._semaphore = semaphore
        self._cookies_file = cookies_file
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

    async def probe_url(self, url: str, *, extra_options: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self._semaphore:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._extract_info, url, False, None, None, None, extra_options),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                raise DownloadError("yt-dlp URL probe timed out.") from exc

    async def download_video(self, normalized: NormalizedResource, work_dir: Path) -> tuple[Path, MediaMetadata]:
        last_error: DownloadError | DownloadUnavailableError | None = None
        for format_selector, merge_output_format in (
            ("bestvideo+bestaudio/best", "mp4"),
            ("best", None),
            (None, None),
        ):
            try:
                return await self.download_url(
                    normalized.canonical_url,
                    work_dir,
                    normalized_key=normalized.normalized_key,
                    format_selector=format_selector,
                    merge_output_format=merge_output_format,
                )
            except (DownloadError, DownloadUnavailableError) as exc:
                last_error = exc
                context = getattr(exc, "context", {})
                if not context.get("format_unavailable"):
                    raise
                log_event(
                    self._logger,
                    30,
                    "media_download_format_fallback",
                    normalized_key=normalized.normalized_key,
                    canonical_url=normalized.canonical_url,
                    format_selector=format_selector or "<default>",
                )
                continue
        if last_error is not None:
            raise last_error
        raise DownloadError(
            "yt-dlp video download failed.",
            temporary=True,
            context={"normalized_key": normalized.normalized_key, "url": normalized.canonical_url},
        )

    async def download_url(
        self,
        url: str,
        work_dir: Path,
        *,
        normalized_key: str,
        format_selector: str | None,
        merge_output_format: str | None,
        extra_options: dict[str, Any] | None = None,
    ) -> tuple[Path, MediaMetadata]:
        async with self._semaphore:
            log_event(
                self._logger,
                20,
                "download_started",
                normalized_key=normalized_key,
                canonical_url=url,
                format_selector=format_selector or "<default>",
            )
            try:
                info = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._extract_info,
                        url,
                        True,
                        work_dir,
                        format_selector,
                        merge_output_format,
                        extra_options,
                    ),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                raise DownloadError("yt-dlp download timed out.", context={"normalized_key": normalized_key, "url": url}) from exc

            downloaded_path = self._resolve_downloaded_path(work_dir, info)
            log_event(
                self._logger,
                20,
                "download_finished",
                normalized_key=normalized_key,
                file_path=str(downloaded_path),
            )
            return downloaded_path, self._build_metadata(info)

    async def download_audio(
        self,
        url: str,
        work_dir: Path,
        *,
        normalized_key: str,
        extra_options: dict[str, Any] | None = None,
    ) -> tuple[Path, MediaMetadata]:
        last_error: DownloadError | DownloadUnavailableError | None = None
        for format_selector in ("bestaudio/best", "best", None):
            try:
                return await self.download_url(
                    url,
                    work_dir,
                    normalized_key=normalized_key,
                    format_selector=format_selector,
                    merge_output_format=None,
                    extra_options=extra_options,
                )
            except (DownloadError, DownloadUnavailableError) as exc:
                last_error = exc
                context = getattr(exc, "context", {})
                if not context.get("format_unavailable"):
                    raise
                log_event(
                    self._logger,
                    30,
                    "media_download_format_fallback",
                    normalized_key=normalized_key,
                    canonical_url=url,
                    format_selector=format_selector or "<default>",
                )
                continue
        if last_error is not None:
            raise last_error
        raise DownloadError("yt-dlp audio download failed.", temporary=True, context={"normalized_key": normalized_key, "url": url})

    def _extract_info(
        self,
        url: str,
        download: bool,
        work_dir: Path | None,
        format_selector: str | None = "bestvideo+bestaudio/best",
        merge_output_format: str | None = "mp4",
        extra_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        options = self._build_options(
            download=download,
            work_dir=work_dir,
            format_selector=format_selector,
            merge_output_format=merge_output_format,
            extra_options=extra_options,
        )
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=download)
        except yt_dlp.utils.DownloadError as exc:
            message = str(exc)
            lower = message.lower()
            if any(marker in lower for marker in ("requested format is not available", "no video formats found")):
                raise DownloadError(
                    message,
                    temporary=True,
                    context={"url": url, "format_unavailable": True, "format_selector": format_selector},
                ) from exc
            if any(marker in lower for marker in ("video unavailable", "status code 404", "unable to extract url")):
                raise DownloadUnavailableError(message) from exc
            if any(marker in lower for marker in ("private", "login required", "sign in", "not available")):
                raise DownloadError(message, temporary=False, context={"url": url, "format_selector": format_selector}) from exc
            if any(marker in lower for marker in ("timed out", "429", "too many requests", "temporary")):
                raise DownloadError(message, temporary=True, context={"url": url, "format_selector": format_selector}) from exc
            raise DownloadError(message, temporary=True, context={"url": url, "format_selector": format_selector}) from exc
        return info

    def _build_options(
        self,
        *,
        download: bool,
        work_dir: Path | None,
        format_selector: str | None,
        merge_output_format: str | None,
        extra_options: dict[str, Any] | None,
    ) -> dict[str, Any]:
        outtmpl = None if work_dir is None else str(work_dir / "%(id)s.%(ext)s")
        options: dict[str, Any] = {
            "paths": {"home": str(work_dir)} if work_dir is not None else None,
            "outtmpl": outtmpl,
            "format": format_selector,
            "merge_output_format": merge_output_format,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "socket_timeout": self._timeout_seconds,
            "extractor_retries": 3,
            "cachedir": False,
        }
        if self._cookies_file is not None and self._cookies_file.exists():
            options["cookiefile"] = str(self._cookies_file)
        if extra_options:
            options.update(extra_options)
        return {key: value for key, value in options.items() if value is not None}

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
