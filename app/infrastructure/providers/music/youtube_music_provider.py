from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import yt_dlp

from app.domain.entities.music_track import MusicTrack
from app.domain.enums import MusicFailureCode
from app.domain.errors import MusicDownloadError
from app.infrastructure.downloaders.ytdlp_music_error_parser import classify_ytdlp_music_error
from app.infrastructure.downloaders.ytdlp_music_options import build_music_ytdlp_options
from app.infrastructure.logging import get_logger, log_event


class YouTubeMusicProvider:
    provider_name = "youtube"

    def __init__(self, *, timeout_seconds: int, semaphore: asyncio.Semaphore) -> None:
        self._timeout_seconds = timeout_seconds
        self._semaphore = semaphore
        self._logger = get_logger(__name__)

    async def resolve_candidates(
        self,
        query: str,
        *,
        max_candidates: int,
        cookies_file: Path | None = None,
    ) -> list[MusicTrack]:
        async with self._semaphore:
            log_event(
                self._logger,
                logging.INFO,
                "music_search_started",
                query=query,
                max_candidates=max_candidates,
                cookies_enabled=cookies_file is not None,
            )
            try:
                info = await asyncio.wait_for(
                    asyncio.to_thread(self._search, query, max_candidates, cookies_file),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                raise MusicDownloadError(
                    "Music search timed out.",
                    error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
                    context={"query": query},
                ) from exc
            tracks = self._extract_candidates(info, max_candidates=max_candidates)
            log_event(
                self._logger,
                logging.INFO,
                "music_search_finished",
                query=query,
                found=bool(tracks),
                candidate_count=len(tracks),
                source_ids=[track.source_id for track in tracks],
            )
            return tracks

    def _search(self, query: str, max_candidates: int, cookies_file: Path | None) -> dict[str, Any]:
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
        }
        options = build_music_ytdlp_options(
            options,
            cookies_file=cookies_file,
            logger=self._logger,
            operation="music_search",
        )
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                return ydl.extract_info(f"ytsearch{max_candidates}:{query}", download=False)
        except yt_dlp.utils.DownloadError as exc:
            error_code = classify_ytdlp_music_error(str(exc))
            raise MusicDownloadError(
                str(exc),
                error_code=error_code.value,
                context={"query": query},
            ) from exc

    @staticmethod
    def _extract_candidates(info: dict[str, Any], *, max_candidates: int) -> list[MusicTrack]:
        entry = info
        if info.get("_type") == "playlist":
            entries = info.get("entries") or []
        else:
            entries = [entry]

        candidates: list[MusicTrack] = []
        for rank, item in enumerate((candidate for candidate in entries if candidate), start=1):
            source_id = str(item.get("id") or "").strip()
            if not source_id:
                continue
            title = str(item.get("track") or item.get("title") or "").strip()
            if not title:
                continue
            performer = _pick_first(item, "artist", "uploader", "channel", "creator")
            thumbnail_url = item.get("thumbnail")
            if thumbnail_url is None:
                thumbnails = item.get("thumbnails") or []
                if thumbnails:
                    thumbnail_url = thumbnails[-1].get("url")
            source_url = str(item.get("webpage_url") or f"https://www.youtube.com/watch?v={source_id}")
            candidates.append(
                MusicTrack(
                    source_id=source_id,
                    source_url=source_url,
                    canonical_url=f"https://music.youtube.com/watch?v={source_id}",
                    title=title,
                    performer=performer,
                    duration_sec=item.get("duration"),
                    thumbnail_url=thumbnail_url,
                    resolver_name="youtube_search",
                    source_name="youtube",
                    ranking=rank,
                )
            )
            if len(candidates) >= max_candidates:
                break
        return candidates


def _pick_first(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
