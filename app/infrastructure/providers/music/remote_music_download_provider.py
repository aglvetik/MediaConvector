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


class RemoteMusicDownloadProvider:
    provider_name = "remote_http"

    def __init__(
        self,
        *,
        endpoint_url: str | None,
        access_token: str | None,
        timeout_seconds: int,
        semaphore: asyncio.Semaphore,
    ) -> None:
        self._endpoint_url = endpoint_url.strip() if endpoint_url else None
        self._access_token = access_token.strip() if access_token else None
        self._timeout_seconds = timeout_seconds
        self._semaphore = semaphore
        self._logger = get_logger(__name__)

    @property
    def is_configured(self) -> bool:
        return bool(self._endpoint_url)

    async def skip_reason(self) -> str | None:
        if self.is_configured:
            return None
        return "provider_not_configured"

    async def download_track_audio(
        self,
        query: MusicSearchQuery,
        candidate: MusicTrack,
        work_dir: Path,
        *,
        cookies_file: Path | None = None,
    ) -> MusicDownloadArtifact:
        del cookies_file
        if not self._endpoint_url:
            raise MusicDownloadError(
                "Remote music download provider is not configured.",
                error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
                user_message=messages.MUSIC_SOURCE_DEGRADED,
            )

        payload = {
            "query": query.raw_query,
            "normalized_query": query.normalized_resource.normalized_key,
            "candidate": {
                "source_id": candidate.source_id,
                "source_url": candidate.source_url,
                "canonical_url": candidate.canonical_url,
                "title": candidate.title,
                "performer": candidate.performer,
                "duration_sec": candidate.duration_sec,
                "thumbnail_url": candidate.thumbnail_url,
                "resolver_name": candidate.resolver_name,
                "source_name": candidate.source_name,
                "ranking": candidate.ranking,
            },
        }
        headers = {"Accept": "application/json, audio/*, application/octet-stream"}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        async with self._semaphore:
            log_event(
                self._logger,
                logging.INFO,
                "music_remote_download_started",
                provider_name=self.provider_name,
                source_id=candidate.source_id,
                endpoint_url=self._endpoint_url,
            )
            try:
                async with httpx.AsyncClient(timeout=self._timeout_seconds, follow_redirects=True) as client:
                    response = await client.post(self._endpoint_url, json=payload, headers=headers)
                    response.raise_for_status()
                    artifact = await self._build_artifact_from_response(client, response, work_dir, candidate)
            except httpx.TimeoutException as exc:
                raise MusicDownloadError(
                    "Remote music provider timed out.",
                    error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
                    user_message=messages.MUSIC_SOURCE_DEGRADED,
                    context={"provider_name": self.provider_name},
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise MusicDownloadError(
                    f"Remote music provider returned HTTP {exc.response.status_code}.",
                    error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
                    user_message=messages.MUSIC_SOURCE_DEGRADED,
                    context={"provider_name": self.provider_name, "status_code": exc.response.status_code},
                ) from exc
            except httpx.HTTPError as exc:
                raise MusicDownloadError(
                    "Remote music provider request failed.",
                    error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
                    user_message=messages.MUSIC_SOURCE_DEGRADED,
                    context={"provider_name": self.provider_name},
                ) from exc

        log_event(
            self._logger,
            logging.INFO,
            "music_remote_download_finished",
            provider_name=self.provider_name,
            source_id=candidate.source_id,
            file_path=str(artifact.source_audio_path),
        )
        return artifact

    async def _build_artifact_from_response(
        self,
        client: httpx.AsyncClient,
        response: httpx.Response,
        work_dir: Path,
        candidate: MusicTrack,
    ) -> MusicDownloadArtifact:
        content_type = (response.headers.get("content-type") or "").lower()
        if "application/json" in content_type:
            try:
                data = response.json()
            except ValueError as exc:
                raise MusicDownloadError(
                    "Remote music provider returned invalid JSON.",
                    error_code=MusicFailureCode.DOWNLOAD_FAILED.value,
                    user_message=messages.MUSIC_DOWNLOAD_FAILED,
                    context={"provider_name": self.provider_name},
                ) from exc
            download_url = str(data.get("download_url") or data.get("audio_url") or "").strip()
            if not download_url:
                raise MusicDownloadError(
                    "Remote music provider JSON response is missing download_url.",
                    error_code=MusicFailureCode.DOWNLOAD_FAILED.value,
                    user_message=messages.MUSIC_DOWNLOAD_FAILED,
                    context={"provider_name": self.provider_name},
                )
            download_response = await client.get(download_url)
            download_response.raise_for_status()
            return self._write_audio_response(
                download_response,
                work_dir,
                candidate,
                metadata=data,
            )
        return self._write_audio_response(response, work_dir, candidate, metadata=None)

    def _write_audio_response(
        self,
        response: httpx.Response,
        work_dir: Path,
        candidate: MusicTrack,
        *,
        metadata: dict[str, Any] | None,
    ) -> MusicDownloadArtifact:
        file_name = _pick_file_name(response, metadata, candidate)
        target_path = work_dir / file_name
        target_path.write_bytes(response.content)
        if target_path.stat().st_size == 0:
            raise MusicDownloadError(
                "Remote music provider returned an empty audio payload.",
                error_code=MusicFailureCode.DOWNLOAD_FAILED.value,
                user_message=messages.MUSIC_DOWNLOAD_FAILED,
                context={"provider_name": self.provider_name},
            )
        metadata = metadata or {}
        return MusicDownloadArtifact(
            source_audio_path=target_path,
            provider_name=self.provider_name,
            title=_normalize_optional_text(metadata.get("title")),
            performer=_normalize_optional_text(metadata.get("performer")),
            thumbnail_url=_normalize_optional_text(metadata.get("thumbnail_url")),
            canonical_url=_normalize_optional_text(metadata.get("canonical_url")),
            source_id=_normalize_optional_text(metadata.get("source_id")),
            source_name=_normalize_optional_text(metadata.get("source_name")) or self.provider_name,
        )


def _pick_file_name(response: httpx.Response, metadata: dict[str, Any] | None, candidate: MusicTrack) -> str:
    metadata = metadata or {}
    raw_name = _normalize_optional_text(metadata.get("file_name"))
    if raw_name:
        target = Path(raw_name)
        if target.suffix:
            return target.name

    content_disposition = response.headers.get("content-disposition") or ""
    if "filename=" in content_disposition:
        _, _, tail = content_disposition.partition("filename=")
        raw_filename = tail.strip().strip("\"'")
        if raw_filename:
            return Path(raw_filename).name

    source_url = str(metadata.get("download_url") or response.request.url)
    parsed = urlparse(source_url)
    suffix = Path(parsed.path).suffix
    if not suffix:
        suffix = _suffix_from_content_type(response.headers.get("content-type"))
    base_name = candidate.source_id or "remote-track"
    return f"{base_name}{suffix or '.bin'}"


def _suffix_from_content_type(content_type: str | None) -> str:
    lowered = (content_type or "").lower()
    if "mpeg" in lowered or "mp3" in lowered:
        return ".mp3"
    if "mp4" in lowered or "m4a" in lowered:
        return ".m4a"
    if "aac" in lowered:
        return ".aac"
    if "ogg" in lowered:
        return ".ogg"
    if "webm" in lowered:
        return ".webm"
    return ""


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
