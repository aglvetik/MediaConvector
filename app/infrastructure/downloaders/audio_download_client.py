from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx
import yt_dlp

from app.domain.entities.music_download_artifact import MusicDownloadArtifact
from app.domain.entities.music_search_query import MusicSearchQuery
from app.domain.entities.music_track import MusicTrack
from app.domain.errors import MusicDownloadError
from app.domain.enums import MusicFailureCode
from app.infrastructure.downloaders.ytdlp_music_error_parser import classify_ytdlp_music_error
from app.infrastructure.downloaders.ytdlp_music_options import build_music_ytdlp_options
from app.infrastructure.logging import get_logger, log_event


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

    async def download_track_audio(
        self,
        query: MusicSearchQuery,
        candidate: MusicTrack,
        work_dir: Path,
        *,
        cookies_file: Path | None = None,
    ) -> MusicDownloadArtifact:
        del query
        source_path = await self.download_audio_source(
            candidate,
            work_dir,
            cookies_file=cookies_file,
        )
        return MusicDownloadArtifact(
            source_audio_path=source_path,
            provider_name="youtube_direct",
            canonical_url=candidate.canonical_url,
            source_id=candidate.source_id,
            source_name=candidate.source_name,
        )

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
        options = self._build_download_options(work_dir, cookies_file)
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
                    "format_selector": options.get("format"),
                },
            )
            self._log_available_formats(source_url, cookies_file)
            raise MusicDownloadError(
                str(exc),
                error_code=error_code.value,
                context={"source_url": source_url, "format_selector": options.get("format")},
            ) from exc

    def _build_download_options(self, work_dir: Path, cookies_file: Path | None) -> dict[str, Any]:
        # Prefer a single minimal selector that matches the known-good manual yt-dlp behavior
        # more closely than direct-audio-only selection. ffmpeg will extract/transcode later.
        base_options: dict[str, Any] = {
            "paths": {"home": str(work_dir)},
            "outtmpl": str(work_dir / "source.%(ext)s"),
            "format": self._build_format_selector(),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": self._timeout_seconds,
        }
        return build_music_ytdlp_options(
            base_options,
            cookies_file=cookies_file,
            logger=self._logger,
            operation="music_download",
        )

    def _build_format_selector(self) -> str:
        return "best"

    def _log_available_formats(self, source_url: str, cookies_file: Path | None) -> None:
        if not self._logger.isEnabledFor(logging.DEBUG):
            return

        diagnostic_options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": self._timeout_seconds,
        }
        diagnostic_options = build_music_ytdlp_options(
            diagnostic_options,
            cookies_file=cookies_file,
            logger=self._logger,
            operation="music_download_diagnostics",
        )
        try:
            with yt_dlp.YoutubeDL(diagnostic_options) as ydl:
                info = ydl.extract_info(source_url, download=False)
        except Exception:
            self._logger.debug(
                "yt_dlp_available_formats_failed",
                exc_info=True,
                extra={"source_url": source_url},
            )
            return

        formats = info.get("formats") or []
        summarized_formats = [
            {
                "format_id": item.get("format_id"),
                "ext": item.get("ext"),
                "acodec": item.get("acodec"),
                "vcodec": item.get("vcodec"),
                "format_note": item.get("format_note"),
                "abr": item.get("abr"),
                "tbr": item.get("tbr"),
                "height": item.get("height"),
                "protocol": item.get("protocol"),
            }
            for item in formats[:12]
        ]
        log_event(
            self._logger,
            logging.DEBUG,
            "music_download_available_formats",
            source_url=source_url,
            format_count=len(formats),
            formats=summarized_formats,
        )

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
