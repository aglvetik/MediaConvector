from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from app import messages
from app.domain.entities.music_download_artifact import MusicDownloadArtifact
from app.domain.entities.music_search_query import MusicSearchQuery
from app.domain.entities.music_track import MusicTrack
from app.domain.enums import MusicFailureCode
from app.domain.errors import MusicDownloadError
from app.infrastructure.logging import get_logger, log_event


class InternetArchiveMusicProvider:
    provider_name = "internet_archive"
    _search_url = "https://archive.org/advancedsearch.php"
    _metadata_url = "https://archive.org/metadata/{identifier}"
    _details_url = "https://archive.org/details/{identifier}"
    _download_url = "https://archive.org/download/{identifier}/{file_name}"
    _image_url = "https://archive.org/services/img/{identifier}"

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
        del cookies_file
        params: list[tuple[str, str]] = [
            ("q", _build_archive_query(query)),
            ("rows", str(max(max_candidates * 3, 6))),
            ("page", "1"),
            ("output", "json"),
            ("sort[]", "downloads desc"),
            ("fl[]", "identifier"),
            ("fl[]", "title"),
            ("fl[]", "creator"),
            ("fl[]", "mediatype"),
        ]
        log_event(
            self._logger,
            logging.INFO,
            "music_search_started",
            provider_name=self.provider_name,
            query=query,
            max_candidates=max_candidates,
        )
        payload = await self._request_json(self._search_url, params=params)
        documents = _extract_documents(payload)
        candidates: list[MusicTrack] = []
        for document in documents:
            if len(candidates) >= max_candidates:
                break
            candidate = await self._build_candidate(document, rank=len(candidates) + 1)
            if candidate is not None:
                candidates.append(candidate)
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
                "Internet Archive provider received a candidate from another source.",
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
                    "Internet Archive audio download timed out.",
                    error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
                    user_message=messages.MUSIC_SOURCE_DEGRADED,
                    context={"provider_name": self.provider_name, "source_id": candidate.source_id},
                ) from exc
            except httpx.HTTPError as exc:
                raise MusicDownloadError(
                    "Internet Archive audio download failed.",
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
                "Internet Archive returned an empty audio file.",
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

    async def _build_candidate(self, document: dict[str, Any], *, rank: int) -> MusicTrack | None:
        identifier = _normalize_optional_text(document.get("identifier"))
        if identifier is None:
            return None
        metadata = await self._request_json(self._metadata_url.format(identifier=identifier))
        selected_file = _select_audio_file(metadata.get("files"))
        if selected_file is None:
            return None
        title = (
            _normalize_optional_text(document.get("title"))
            or _normalize_optional_text((metadata.get("metadata") or {}).get("title"))
            or identifier
        )
        performer = _normalize_creator(document.get("creator"))
        if performer is None:
            performer = _normalize_creator((metadata.get("metadata") or {}).get("creator"))
        file_name = str(selected_file.get("name") or "").strip()
        if not file_name:
            return None
        return MusicTrack(
            source_id=identifier,
            source_url=self._download_url.format(identifier=identifier, file_name=quote(file_name, safe="/")),
            canonical_url=self._details_url.format(identifier=identifier),
            title=title,
            performer=performer,
            duration_sec=_normalize_length(selected_file.get("length")),
            thumbnail_url=self._image_url.format(identifier=identifier),
            resolver_name="internet_archive_search",
            source_name=self.provider_name,
            ranking=rank,
        )

    async def _request_json(self, url: str, *, params: list[tuple[str, str]] | None = None) -> dict[str, Any]:
        async with self._semaphore:
            try:
                async with httpx.AsyncClient(timeout=self._timeout_seconds, follow_redirects=True) as client:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise MusicDownloadError(
                    "Internet Archive request timed out.",
                    error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
                    user_message=messages.MUSIC_SOURCE_DEGRADED,
                    context={"provider_name": self.provider_name, "url": url},
                ) from exc
            except httpx.HTTPError as exc:
                raise MusicDownloadError(
                    "Internet Archive request failed.",
                    error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
                    user_message=messages.MUSIC_SOURCE_DEGRADED,
                    context={"provider_name": self.provider_name, "url": url},
                ) from exc
        try:
            return response.json()
        except ValueError as exc:
            raise MusicDownloadError(
                "Internet Archive returned invalid JSON.",
                error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
                user_message=messages.MUSIC_SOURCE_DEGRADED,
                context={"provider_name": self.provider_name, "url": url},
            ) from exc


def _build_archive_query(query: str) -> str:
    sanitized = " ".join(query.split()).replace('"', " ")
    if not sanitized:
        return "mediatype:(audio)"
    return f'mediatype:(audio) AND "{sanitized}"'


def _extract_documents(payload: dict[str, Any]) -> list[dict[str, Any]]:
    response = payload.get("response")
    if not isinstance(response, dict):
        return []
    documents = response.get("docs")
    if not isinstance(documents, list):
        return []
    return [document for document in documents if isinstance(document, dict)]


def _select_audio_file(files: object) -> dict[str, Any] | None:
    if not isinstance(files, list):
        return None
    scored: list[tuple[int, dict[str, Any]]] = []
    for file_info in files:
        if not isinstance(file_info, dict):
            continue
        name = _normalize_optional_text(file_info.get("name"))
        if name is None:
            continue
        score = _score_audio_file(file_info)
        if score is None:
            continue
        scored.append((score, file_info))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0])
    return scored[0][1]


def _score_audio_file(file_info: dict[str, Any]) -> int | None:
    name = _normalize_optional_text(file_info.get("name"))
    if name is None:
        return None
    suffix = Path(name).suffix.casefold()
    if suffix not in {".mp3", ".ogg", ".flac", ".m4a", ".aac", ".wav", ".opus", ".webm"}:
        return None
    if any(marker in name.casefold() for marker in ("_spectrogram", "_thumb", ".torrent")):
        return None
    source_rank = 0 if str(file_info.get("source") or "").casefold() == "original" else 10
    ext_rank = {
        ".mp3": 0,
        ".ogg": 1,
        ".flac": 2,
        ".m4a": 3,
        ".aac": 4,
        ".opus": 5,
        ".wav": 6,
        ".webm": 7,
    }[suffix]
    format_value = str(file_info.get("format") or "").casefold()
    derivative_penalty = 5 if "metadata" in format_value or "jpeg" in format_value else 0
    return source_rank + ext_rank + derivative_penalty


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_creator(value: object) -> str | None:
    if isinstance(value, list):
        for item in value:
            normalized = _normalize_optional_text(item)
            if normalized:
                return normalized
        return None
    return _normalize_optional_text(value)


def _normalize_length(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
        parts = stripped.split(":")
        if all(part.isdigit() for part in parts):
            total = 0
            for part in parts:
                total = total * 60 + int(part)
            return total
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
    if "wav" in lowered:
        return ".wav"
    return ""
