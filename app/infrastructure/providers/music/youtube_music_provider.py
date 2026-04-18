from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import yt_dlp

from app.domain.entities.music_track import MusicTrack
from app.domain.errors import MusicDownloadError
from app.infrastructure.downloaders.ytdlp_music_options import build_music_ytdlp_options
from app.infrastructure.logging import get_logger, log_event


class YouTubeMusicProvider:
    provider_name = "ytmusic"

    def __init__(self, *, timeout_seconds: int, semaphore: asyncio.Semaphore, cookies_file: Path | None = None) -> None:
        self._timeout_seconds = timeout_seconds
        self._semaphore = semaphore
        self._cookies_file = cookies_file
        self._logger = get_logger(__name__)

    async def search_best_match(self, query: str) -> MusicTrack | None:
        async with self._semaphore:
            log_event(self._logger, logging.INFO, "music_search_started", query=query)
            try:
                info = await asyncio.wait_for(
                    asyncio.to_thread(self._search, query),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                raise MusicDownloadError("Music search timed out.", context={"query": query}) from exc
            track = self._extract_best_track(info)
            log_event(
                self._logger,
                logging.INFO,
                "music_search_finished",
                query=query,
                found=track is not None,
                source_id=track.source_id if track else None,
            )
            return track

    def _search(self, query: str) -> dict[str, Any]:
        # Keep the search path close to the known-good standalone yt-dlp usage.
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
        }
        options = build_music_ytdlp_options(
            options,
            cookies_file=self._cookies_file,
            logger=self._logger,
            operation="music_search",
        )
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                return ydl.extract_info(f"ytsearch1:{query}", download=False)
        except yt_dlp.utils.DownloadError as exc:
            raise MusicDownloadError(str(exc), context={"query": query}) from exc

    @staticmethod
    def _extract_best_track(info: dict[str, Any]) -> MusicTrack | None:
        entry = info
        if info.get("_type") == "playlist":
            entries = info.get("entries") or []
            entry = next((item for item in entries if item), None)
        if not entry:
            return None
        source_id = str(entry.get("id") or "").strip()
        if not source_id:
            return None
        title = str(entry.get("track") or entry.get("title") or "").strip()
        if not title:
            return None
        performer = _pick_first(entry, "artist", "uploader", "channel", "creator")
        thumbnail_url = entry.get("thumbnail")
        if thumbnail_url is None:
            thumbnails = entry.get("thumbnails") or []
            if thumbnails:
                thumbnail_url = thumbnails[-1].get("url")
        source_url = str(entry.get("webpage_url") or f"https://www.youtube.com/watch?v={source_id}")
        canonical_url = f"https://music.youtube.com/watch?v={source_id}"
        return MusicTrack(
            source_id=source_id,
            source_url=source_url,
            canonical_url=canonical_url,
            title=title,
            performer=performer,
            duration_sec=entry.get("duration"),
            thumbnail_url=thumbnail_url,
        )


def _pick_first(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
