from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app import messages
from app.domain.entities.music_download_artifact import MusicDownloadArtifact
from app.domain.entities.music_search_query import MusicSearchQuery
from app.domain.entities.music_track import MusicTrack
from app.domain.enums import MusicFailureCode
from app.domain.errors import MusicDownloadError
from app.infrastructure.logging import get_logger, log_event


class JamendoMusicProvider:
    provider_name = "jamendo"
    _api_url = "https://api.jamendo.com/v3.0/tracks/"

    def __init__(
        self,
        *,
        client_id: str | None,
        timeout_seconds: int,
        semaphore: asyncio.Semaphore,
    ) -> None:
        self._client_id = client_id.strip() if client_id else None
        self._timeout_seconds = timeout_seconds
        self._semaphore = semaphore
        self._logger = get_logger(__name__)

    async def skip_reason(self) -> str | None:
        if self._client_id:
            return None
        return "provider_not_configured"

    async def resolve_candidates(
        self,
        query: str,
        *,
        max_candidates: int,
        cookies_file: Path | None = None,
    ) -> list[MusicTrack]:
        del cookies_file
        if self._client_id is None:
            return []

        params = {
            "client_id": self._client_id,
            "format": "json",
            "limit": min(max_candidates * 4, 20),
            "namesearch": query,
            "order": "relevance",
            "type": "single albumtrack",
            "imagesize": "300",
            "audiodlformat": "mp32",
        }
        log_event(
            self._logger,
            logging.INFO,
            "music_search_started",
            provider_name=self.provider_name,
            query=query,
            max_candidates=max_candidates,
        )
        payload = await self._request_json(params)
        candidates = self._parse_tracks(payload, max_candidates=max_candidates)
        log_event(
            self._logger,
            logging.INFO,
            "music_search_finished",
            provider_name=self.provider_name,
            query=query,
            found=bool(candidates),
            candidate_count=len(candidates),
            source_ids=[track.source_id for track in candidates],
        )
        return candidates

    async def download_track_audio(
        self,
        query: MusicSearchQuery,
        candidate: MusicTrack,
        work_dir: Path,
        *,
        cookies_file: Path | None = None,
    ) -> MusicDownloadArtifact:
        del query
        del cookies_file
        if candidate.source_name != self.provider_name:
            raise MusicDownloadError(
                "Jamendo provider received a candidate from another source.",
                error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
                user_message=messages.MUSIC_DOWNLOAD_FAILED,
            )
        async with self._semaphore:
            try:
                async with httpx.AsyncClient(timeout=self._timeout_seconds, follow_redirects=True) as client:
                    response = await client.get(candidate.source_url)
                    response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise MusicDownloadError(
                    "Jamendo audio download timed out.",
                    error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
                    user_message=messages.MUSIC_SOURCE_DEGRADED,
                    context={"provider_name": self.provider_name, "source_id": candidate.source_id},
                ) from exc
            except httpx.HTTPError as exc:
                raise MusicDownloadError(
                    "Jamendo audio download failed.",
                    error_code=MusicFailureCode.DOWNLOAD_FAILED.value,
                    user_message=messages.MUSIC_DOWNLOAD_FAILED,
                    context={"provider_name": self.provider_name, "source_id": candidate.source_id},
                ) from exc

        suffix = Path(urlparse(candidate.source_url).path).suffix or _suffix_from_content_type(
            response.headers.get("content-type")
        )
        target_path = work_dir / f"{candidate.source_id}{suffix or '.mp3'}"
        target_path.write_bytes(response.content)
        if target_path.stat().st_size == 0:
            raise MusicDownloadError(
                "Jamendo returned an empty audio file.",
                error_code=MusicFailureCode.DOWNLOAD_FAILED.value,
                user_message=messages.MUSIC_DOWNLOAD_FAILED,
                context={"provider_name": self.provider_name, "source_id": candidate.source_id},
            )
        return MusicDownloadArtifact(
            source_audio_path=target_path,
            provider_name=self.provider_name,
            title=candidate.title,
            performer=candidate.performer,
            thumbnail_url=candidate.thumbnail_url,
            canonical_url=candidate.canonical_url,
            source_id=candidate.source_id,
            source_name=self.provider_name,
        )

    async def _request_json(self, params: dict[str, Any]) -> dict[str, Any]:
        async with self._semaphore:
            try:
                async with httpx.AsyncClient(timeout=self._timeout_seconds, follow_redirects=True) as client:
                    response = await client.get(self._api_url, params=params)
                    response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise MusicDownloadError(
                    "Jamendo search timed out.",
                    error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
                    user_message=messages.MUSIC_SOURCE_DEGRADED,
                    context={"provider_name": self.provider_name},
                ) from exc
            except httpx.HTTPError as exc:
                raise MusicDownloadError(
                    "Jamendo search request failed.",
                    error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
                    user_message=messages.MUSIC_SOURCE_DEGRADED,
                    context={"provider_name": self.provider_name},
                ) from exc

        try:
            return response.json()
        except ValueError as exc:
            raise MusicDownloadError(
                "Jamendo returned invalid JSON.",
                error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
                user_message=messages.MUSIC_SOURCE_DEGRADED,
                context={"provider_name": self.provider_name},
            ) from exc

    def _parse_tracks(self, payload: dict[str, Any], *, max_candidates: int) -> list[MusicTrack]:
        headers = payload.get("headers") or {}
        if headers.get("status") not in {None, "success"}:
            raise MusicDownloadError(
                "Jamendo search returned an API error.",
                error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
                user_message=messages.MUSIC_SOURCE_DEGRADED,
                context={"provider_name": self.provider_name, "headers": headers},
            )

        results = payload.get("results")
        if not isinstance(results, list):
            return []

        candidates: list[MusicTrack] = []
        for rank, item in enumerate(results, start=1):
            if not _is_downloadable_track(item):
                continue
            source_id = str(item.get("id") or "").strip()
            title = str(item.get("name") or "").strip()
            source_url = str(item.get("audiodownload") or "").strip()
            if not source_id or not title or not source_url:
                continue
            performer = _normalize_optional_text(item.get("artist_name"))
            thumbnail_url = (
                _normalize_optional_text(item.get("image"))
                or _normalize_optional_text(item.get("album_image"))
            )
            canonical_url = (
                _normalize_optional_text(item.get("shareurl"))
                or f"https://www.jamendo.com/track/{source_id}"
            )
            candidates.append(
                MusicTrack(
                    source_id=source_id,
                    source_url=source_url,
                    canonical_url=canonical_url,
                    title=title,
                    performer=performer,
                    duration_sec=_normalize_int(item.get("duration")),
                    thumbnail_url=thumbnail_url,
                    resolver_name="jamendo_search",
                    source_name=self.provider_name,
                    ranking=rank,
                )
            )
            if len(candidates) >= max_candidates:
                break
        return candidates


def _is_downloadable_track(item: dict[str, Any]) -> bool:
    allowed = item.get("audiodownload_allowed")
    if allowed not in {True, 1, "1", "true", "True"}:
        return False
    audiodownload = item.get("audiodownload")
    return isinstance(audiodownload, str) and bool(audiodownload.strip())


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _suffix_from_content_type(content_type: str | None) -> str:
    lowered = (content_type or "").lower()
    if "mpeg" in lowered or "mp3" in lowered:
        return ".mp3"
    if "ogg" in lowered:
        return ".ogg"
    if "flac" in lowered:
        return ".flac"
    if "mp4" in lowered or "m4a" in lowered:
        return ".m4a"
    return ""
