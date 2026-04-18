from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import yt_dlp

from app.domain.entities.track_search_candidate import TrackSearchCandidate
from app.domain.errors import TrackDownloadError, TrackNotFoundError
from app.domain.policies import rank_track_candidates
from app.infrastructure.logging import get_logger, log_event


class YoutubeTrackClient:
    def __init__(
        self,
        *,
        timeout_seconds: int,
        semaphore: asyncio.Semaphore,
        cookies_file: Path | None = None,
        search_results_limit: int = 5,
        min_duration_seconds: int = 60,
        max_duration_seconds: int = 12 * 60,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._semaphore = semaphore
        self._cookies_file = cookies_file
        self._search_results_limit = search_results_limit
        self._min_duration_seconds = min_duration_seconds
        self._max_duration_seconds = max_duration_seconds
        self._logger = get_logger(__name__)

    async def search_candidates(self, query: str, *, normalized_key: str) -> list[TrackSearchCandidate]:
        async with self._semaphore:
            cookiefile = self._resolve_cookiefile(operation="track_search")
            log_event(
                self._logger,
                20,
                "music_search_started",
                normalized_key=normalized_key,
                query=query,
                cookies_enabled=cookiefile is not None,
                cookies_path=str(cookiefile) if cookiefile is not None else None,
            )
            try:
                info = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._extract_info,
                        f"ytsearch{self._search_results_limit}:{query}",
                        False,
                        None,
                        "track_search",
                        None,
                    ),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                raise TrackDownloadError("YouTube search timed out.") from exc

        entries = info.get("entries") if isinstance(info, dict) else None
        candidates = self._build_candidates(entries or [])
        ranked = rank_track_candidates(
            query=query,
            candidates=candidates,
            min_duration_seconds=self._min_duration_seconds,
            max_duration_seconds=self._max_duration_seconds,
        )
        log_event(
            self._logger,
            20,
            "music_search_finished",
            normalized_key=normalized_key,
            query=query,
            candidates=len(ranked),
            candidate_ids=[candidate.source_id for candidate in ranked],
        )
        log_event(
            self._logger,
            20,
            "music_search_completed",
            normalized_key=normalized_key,
            query=query,
            candidates=len(ranked),
        )
        return ranked

    async def search(self, query: str, *, normalized_key: str) -> TrackSearchCandidate:
        ranked = await self.search_candidates(query, normalized_key=normalized_key)
        if not ranked:
            raise TrackNotFoundError()
        candidate = ranked[0]
        log_event(
            self._logger,
            20,
            "music_candidate_selected",
            normalized_key=normalized_key,
            source_url=candidate.source_url,
            title=candidate.title,
            uploader=candidate.uploader,
            source_id=candidate.source_id,
            score=candidate.score,
        )
        return candidate

    async def download_audio(self, source_url: str, work_dir: Path, *, normalized_key: str) -> Path:
        format_selectors: tuple[str | None, ...] = ("bestaudio/best", "best", None)
        last_error: TrackDownloadError | None = None

        for format_selector in format_selectors:
            async with self._semaphore:
                cookiefile = self._resolve_cookiefile(operation="track_download")
                selector_label = format_selector or "<default>"
                log_event(
                    self._logger,
                    20,
                    "music_download_started",
                    normalized_key=normalized_key,
                    source_url=source_url,
                    cookies_enabled=cookiefile is not None,
                    cookies_path=str(cookiefile) if cookiefile is not None else None,
                    format_selector=selector_label,
                )
                log_event(
                    self._logger,
                    20,
                    "music_download_format_attempt",
                    normalized_key=normalized_key,
                    source_url=source_url,
                    format_selector=selector_label,
                )
                try:
                    info = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._extract_info,
                            source_url,
                            True,
                            work_dir,
                            "track_download",
                            format_selector,
                        ),
                        timeout=self._timeout_seconds,
                    )
                except TimeoutError as exc:
                    raise TrackDownloadError("YouTube download timed out.") from exc
                except TrackDownloadError as exc:
                    last_error = exc
                    if exc.context.get("format_unavailable"):
                        log_event(
                            self._logger,
                            30,
                            "music_download_format_fallback",
                            normalized_key=normalized_key,
                            source_url=source_url,
                            format_selector=selector_label,
                            reason="format_unavailable",
                        )
                        continue
                    raise

            downloaded_path = self._resolve_downloaded_path(work_dir, info)
            log_event(
                self._logger,
                20,
                "music_download_completed",
                normalized_key=normalized_key,
                file_path=str(downloaded_path),
                format_selector=format_selector or "<default>",
            )
            return downloaded_path

        if last_error is not None:
            raise last_error
        raise TrackDownloadError("yt-dlp did not produce a downloadable track.")

    async def download_thumbnail(self, thumbnail_url: str, destination: Path) -> Path:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds, follow_redirects=True) as client:
                response = await client.get(thumbnail_url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TrackDownloadError("Failed to download track thumbnail.") from exc
        destination.write_bytes(response.content)
        return destination

    def _extract_info(
        self,
        url: str,
        download: bool,
        work_dir: Path | None,
        operation: str,
        format_selector: str | None = None,
    ) -> dict[str, Any]:
        options = self._build_options(
            download=download,
            work_dir=work_dir,
            operation=operation,
            format_selector=format_selector,
        )
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                return ydl.extract_info(url, download=download)
        except yt_dlp.utils.DownloadError as exc:
            error_text = str(exc)
            context: dict[str, object] = {"operation": operation}
            if self._is_unavailable_format_error(error_text):
                context["format_unavailable"] = True
            log_event(
                self._logger,
                40,
                "yt_dlp_track_failure",
                operation=operation,
                url=url,
                cookies_enabled="cookiefile" in options,
                cookies_path=options.get("cookiefile"),
                format_selector=options.get("format"),
                error_text=error_text,
            )
            raise TrackDownloadError(error_text, context=context) from exc

    def _build_options(
        self,
        *,
        download: bool,
        work_dir: Path | None,
        operation: str,
        format_selector: str | None = None,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {
            "paths": {"home": str(work_dir)} if work_dir is not None else None,
            "outtmpl": str(work_dir / "%(id)s.%(ext)s") if work_dir is not None else None,
            "format": format_selector,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": self._timeout_seconds,
            "cachedir": False,
            "extract_flat": False if operation == "track_search" else None,
        }
        cookiefile = self._resolve_cookiefile(operation=operation)
        if cookiefile is not None:
            options["cookiefile"] = str(cookiefile)
        return {key: value for key, value in options.items() if value is not None}

    def _resolve_cookiefile(self, *, operation: str) -> Path | None:
        if self._cookies_file is None:
            return None
        if self._cookies_file.exists():
            return self._cookies_file
        log_event(
            self._logger,
            30,
            "cookies_missing",
            operation=operation,
            cookies_path=str(self._cookies_file),
        )
        return None

    @staticmethod
    def _build_candidates(entries: list[object]) -> list[TrackSearchCandidate]:
        candidates: list[TrackSearchCandidate] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            source_id = str(entry.get("id") or "")
            source_url = _canonical_candidate_url(entry, source_id)
            title = str(entry.get("title") or "").strip()
            if not source_url or not source_id or not title:
                continue
            candidates.append(
                TrackSearchCandidate(
                    source_id=source_id,
                    source_url=source_url,
                    title=title,
                    uploader=_clean_optional(entry.get("uploader") or entry.get("channel")),
                    thumbnail_url=_extract_thumbnail(entry),
                    duration_sec=_to_int(entry.get("duration")),
                    score=0,
                )
            )
        return candidates

    @staticmethod
    def _resolve_downloaded_path(work_dir: Path, info: dict[str, Any]) -> Path:
        requested_downloads = info.get("requested_downloads") or []
        for item in requested_downloads:
            if not isinstance(item, dict):
                continue
            filepath = item.get("filepath")
            if filepath:
                return Path(filepath)
        filepath = info.get("_filename") or info.get("filepath")
        if filepath:
            return Path(filepath)
        candidates = sorted(work_dir.glob("*"))
        if not candidates:
            raise TrackDownloadError("yt-dlp finished without producing a file.")
        return candidates[0]

    @staticmethod
    def _is_unavailable_format_error(error_text: str) -> bool:
        lowered = error_text.casefold()
        return "requested format is not available" in lowered or "no video formats found" in lowered


def _clean_optional(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned or None


def _extract_thumbnail(entry: dict[str, Any]) -> str | None:
    thumbnail = entry.get("thumbnail")
    if isinstance(thumbnail, str) and thumbnail.startswith("http"):
        return thumbnail
    thumbnails = entry.get("thumbnails")
    if isinstance(thumbnails, list):
        for item in thumbnails:
            if isinstance(item, dict):
                url = item.get("url")
                if isinstance(url, str) and url.startswith("http"):
                    return url
    return None


def _canonical_candidate_url(entry: dict[str, Any], source_id: str) -> str:
    webpage_url = entry.get("webpage_url")
    if isinstance(webpage_url, str) and webpage_url.startswith("http"):
        return webpage_url

    original_url = entry.get("original_url")
    if isinstance(original_url, str) and original_url.startswith("http"):
        return original_url

    url = entry.get("url")
    if isinstance(url, str):
        if url.startswith("http"):
            return url
        if source_id:
            return f"https://www.youtube.com/watch?v={source_id}"

    if source_id:
        return f"https://www.youtube.com/watch?v={source_id}"
    return ""


def _to_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
