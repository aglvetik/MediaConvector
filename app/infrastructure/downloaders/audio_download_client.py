from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx
import yt_dlp

from app.domain.entities.music_track import MusicTrack
from app.domain.errors import MusicDownloadError
from app.domain.enums import MusicFailureCode
from app.infrastructure.downloaders.ytdlp_music_error_parser import classify_ytdlp_music_error
from app.infrastructure.logging import get_logger, log_event
from app.infrastructure.downloaders.ytdlp_music_options import build_music_ytdlp_options


class AudioDownloadClient:
    def __init__(self, *, timeout_seconds: int, semaphore: asyncio.Semaphore, audio_only: bool = True) -> None:
        self._timeout_seconds = timeout_seconds
        self._semaphore = semaphore
        self._audio_only = audio_only
        self._logger = get_logger(__name__)

    async def download_audio_source(
        self,
        track: MusicTrack,
        work_dir: Path,
        *,
        cookies_file: Path | None = None,
    ) -> Path:
        async with self._semaphore:
            log_event(
                self._logger,
                logging.INFO,
                "music_download_started",
                source_id=track.source_id,
                canonical_url=track.canonical_url,
                cookies_enabled=cookies_file is not None,
                audio_only=self._audio_only,
            )
            try:
                info = await asyncio.wait_for(
                    asyncio.to_thread(self._download_audio, track.source_url, work_dir, cookies_file),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                raise MusicDownloadError(
                    "Music audio download timed out.",
                    error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
                    context={"source_id": track.source_id},
                ) from exc
            downloaded_path = self._resolve_downloaded_path(work_dir, info)
            log_event(
                self._logger,
                logging.INFO,
                "music_download_finished",
                source_id=track.source_id,
                file_path=str(downloaded_path),
            )
            return downloaded_path

    async def download_thumbnail(self, thumbnail_url: str, work_dir: Path, *, fallback_stem: str) -> Path | None:
        output_path = work_dir / f"{fallback_stem}-thumb"
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds, follow_redirects=True) as client:
                response = await client.get(thumbnail_url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            log_event(self._logger, logging.WARNING, "music_thumbnail_download_failed", thumbnail_url=thumbnail_url, error=str(exc))
            return None

        suffix = _guess_image_suffix(response.headers.get("content-type"), thumbnail_url)
        target_path = output_path.with_suffix(suffix)
        target_path.write_bytes(response.content)
        if target_path.stat().st_size == 0:
            return None
        return target_path

    def _download_audio(self, source_url: str, work_dir: Path, cookies_file: Path | None) -> dict[str, Any]:
        option_variants = self._build_download_option_variants(work_dir, cookies_file)
        last_exception: yt_dlp.utils.DownloadError | None = None
        last_error_code = MusicFailureCode.DOWNLOAD_FAILED

        for index, options in enumerate(option_variants):
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    return ydl.extract_info(source_url, download=True)
            except yt_dlp.utils.DownloadError as exc:
                last_exception = exc
                last_error_code = classify_ytdlp_music_error(str(exc))
                self._logger.exception(
                    "yt_dlp_failure",
                    extra={
                        "source_url": source_url,
                        "error_code": last_error_code.value,
                        "raw_error": str(exc),
                        "format_selector": options.get("format"),
                        "attempt_index": index + 1,
                    },
                )
                if last_error_code == MusicFailureCode.NO_FORMATS and index + 1 < len(option_variants):
                    next_format = option_variants[index + 1].get("format")
                    log_event(
                        self._logger,
                        logging.WARNING,
                        "music_download_format_fallback",
                        source_url=source_url,
                        failed_format=options.get("format"),
                        next_format=next_format,
                    )
                    continue
                raise MusicDownloadError(
                    str(exc),
                    error_code=last_error_code.value,
                    context={"source_url": source_url, "format_selector": options.get("format")},
                ) from exc

        if last_exception is None:
            raise MusicDownloadError(
                "Music download failed without executing yt-dlp.",
                context={"source_url": source_url},
            )
        raise MusicDownloadError(
            str(last_exception),
            error_code=last_error_code.value,
            context={"source_url": source_url},
        ) from last_exception

    def _build_download_option_variants(self, work_dir: Path, cookies_file: Path | None) -> list[dict[str, Any]]:
        base_options: dict[str, Any] = {
            "paths": {"home": str(work_dir)},
            "outtmpl": str(work_dir / "source.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "socket_timeout": self._timeout_seconds,
            "extractor_retries": 3,
            "cachedir": False,
        }
        format_selectors = self._build_format_selectors()
        return [
            build_music_ytdlp_options(
                {**base_options, "format": format_selector},
                cookies_file=cookies_file,
                logger=self._logger,
                operation="music_download",
            )
            for format_selector in format_selectors
        ]

    def _build_format_selectors(self) -> tuple[str, ...]:
        if self._audio_only:
            return ("bestaudio/best", "best")
        return ("best",)

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
            raise MusicDownloadError("yt-dlp finished without producing a music source file.")
        return candidates[0]


def _guess_image_suffix(content_type: str | None, thumbnail_url: str) -> str:
    lowered_content_type = (content_type or "").lower()
    if "png" in lowered_content_type or thumbnail_url.lower().endswith(".png"):
        return ".png"
    if "webp" in lowered_content_type or thumbnail_url.lower().endswith(".webp"):
        return ".webp"
    return ".jpg"
