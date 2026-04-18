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
        options: dict[str, Any] = {
            "paths": {"home": str(work_dir)},
            "outtmpl": str(work_dir / "source.%(ext)s"),
            "format": "bestaudio/best" if self._audio_only else "best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "socket_timeout": self._timeout_seconds,
            "extractor_retries": 3,
            "cachedir": False,
        }
        options = build_music_ytdlp_options(
            options,
            cookies_file=cookies_file,
            logger=self._logger,
            operation="music_download",
        )
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                return ydl.extract_info(source_url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            error_code = classify_ytdlp_music_error(str(exc))
            self._logger.exception(
                "yt_dlp_failure",
                extra={
                    "source_url": source_url,
                    "error_code": error_code.value,
                    "raw_error": str(exc),
                },
            )
            raise MusicDownloadError(
                str(exc),
                error_code=error_code.value,
                context={"source_url": source_url},
            ) from exc

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
