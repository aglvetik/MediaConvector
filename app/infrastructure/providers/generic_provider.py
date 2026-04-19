from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.domain.entities.media_result import MediaMetadata
from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.entities.source_media_artifact import SourceMediaArtifact
from app.domain.enums.platform import Platform
from app.domain.errors import DownloadError, NormalizationError, UnsupportedUrlError
from app.domain.policies import build_cache_key
from app.infrastructure.downloaders import YtDlpClient
from app.infrastructure.logging import get_logger, log_event
from app.infrastructure.providers.source_detection import detect_source_type, extract_first_supported_url

_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
_AUDIO_EXTENSIONS = {"mp3", "m4a", "aac", "ogg", "opus", "wav", "flac"}


class YtDlpUrlProvider:
    def __init__(
        self,
        *,
        platform: Platform,
        downloader: YtDlpClient,
        request_timeout_seconds: int,
    ) -> None:
        self.platform_name = platform.value
        self._platform = platform
        self._downloader = downloader
        self._request_timeout_seconds = request_timeout_seconds
        self._logger = get_logger(__name__)

    def extract_first_url(self, text: str) -> str | None:
        return extract_first_supported_url(text, self._platform)

    def can_handle(self, url: str) -> bool:
        return detect_source_type(url) == self._platform

    async def normalize(self, url: str) -> NormalizedResource:
        if not self.can_handle(url):
            raise UnsupportedUrlError()

        info = await self._downloader.probe_url(url)
        artifact = self._build_artifact(url, info)
        if artifact is None:
            raise NormalizationError("The extractor did not return a supported media result.", context={"url": url})

        resource_type = _artifact_to_resource_type(artifact.media_kind)
        normalized = NormalizedResource(
            platform=self._platform,
            resource_type=resource_type,
            resource_id=artifact.source_id,
            normalized_key=build_cache_key(self._platform, resource_type, artifact.source_id),
            original_url=url,
            canonical_url=artifact.canonical_url,
            title=artifact.title,
            author=artifact.uploader,
            audio_url=artifact.canonical_url if artifact.media_kind == "audio" else None,
            image_urls=artifact.image_sources,
            thumbnail_url=artifact.thumbnail_url,
            duration_sec=artifact.duration_sec,
        )
        log_event(
            self._logger,
            20,
            "normalization_completed",
            normalized_key=normalized.normalized_key,
            source_type=self._platform.value,
            canonical_url=normalized.canonical_url,
            media_kind=artifact.media_kind,
        )
        if normalized.resource_type == "photo_post":
            log_event(
                self._logger,
                20,
                "media_gallery_detected",
                normalized_key=normalized.normalized_key,
                source_type=self._platform.value,
                entry_count=len(normalized.image_urls),
            )
        return normalized

    async def fetch_metadata(self, normalized: NormalizedResource) -> MediaMetadata:
        return MediaMetadata(
            title=normalized.title,
            duration_sec=normalized.duration_sec,
            author=normalized.author,
            description=None,
            size_bytes=None,
            has_audio=True if normalized.resource_type == "music_only" else (False if normalized.resource_type == "photo_post" else None),
        )

    async def download_video(self, normalized: NormalizedResource, work_dir: Path) -> Path:
        log_event(
            self._logger,
            20,
            "media_download_started",
            normalized_key=normalized.normalized_key,
            source_type=self._platform.value,
            canonical_url=normalized.canonical_url,
            media_kind="video",
        )
        try:
            path, _ = await self._downloader.download_video(normalized, work_dir)
        except DownloadError as exc:
            log_event(
                self._logger,
                30,
                "media_download_failed",
                normalized_key=normalized.normalized_key,
                source_type=self._platform.value,
                canonical_url=normalized.canonical_url,
                media_kind="video",
                error_code=exc.error_code,
            )
            raise
        log_event(
            self._logger,
            20,
            "media_download_finished",
            normalized_key=normalized.normalized_key,
            source_type=self._platform.value,
            canonical_url=normalized.canonical_url,
            media_kind="video",
            file_path=str(path),
        )
        return path

    async def download_audio(self, normalized: NormalizedResource, work_dir: Path) -> Path | None:
        if normalized.resource_type != "music_only":
            return None
        log_event(
            self._logger,
            20,
            "media_download_started",
            normalized_key=normalized.normalized_key,
            source_type=self._platform.value,
            canonical_url=normalized.canonical_url,
            media_kind="audio",
        )
        try:
            path, _ = await self._downloader.download_audio(
                normalized.canonical_url,
                work_dir,
                normalized_key=normalized.normalized_key,
            )
        except DownloadError as exc:
            log_event(
                self._logger,
                30,
                "media_download_failed",
                normalized_key=normalized.normalized_key,
                source_type=self._platform.value,
                canonical_url=normalized.canonical_url,
                media_kind="audio",
                error_code=exc.error_code,
            )
            raise
        log_event(
            self._logger,
            20,
            "media_download_finished",
            normalized_key=normalized.normalized_key,
            source_type=self._platform.value,
            canonical_url=normalized.canonical_url,
            media_kind="audio",
            file_path=str(path),
        )
        return path

    async def download_images(self, normalized: NormalizedResource, work_dir: Path) -> tuple[Path, ...]:
        paths: list[Path] = []
        for index, image_source in enumerate(normalized.image_urls, start=1):
            try:
                downloaded = await self._download_gallery_entry(
                    image_source,
                    work_dir=work_dir,
                    normalized_key=normalized.normalized_key,
                    file_stem=f"{normalized.resource_id}-image-{index}",
                )
            except DownloadError as exc:
                log_event(
                    self._logger,
                    30,
                    "media_download_failed",
                    normalized_key=normalized.normalized_key,
                    source_type=self._platform.value,
                    canonical_url=image_source,
                    media_kind="photo",
                    error_code=exc.error_code,
                )
                continue
            if _is_image_path(downloaded):
                paths.append(downloaded)
        if not paths:
            raise DownloadError("No gallery images could be downloaded.", temporary=False)
        return tuple(paths)

    def _build_artifact(self, original_url: str, info: dict[str, object]) -> SourceMediaArtifact | None:
        title = _clean_optional(info.get("title"))
        uploader = _clean_optional(info.get("uploader") or info.get("channel") or info.get("artist"))
        thumbnail_url = _extract_thumbnail(info)
        duration_sec = _to_int(info.get("duration"))
        canonical_url = _canonical_url(info, original_url)
        source_id = _clean_optional(info.get("id")) or _fallback_source_id(canonical_url)

        image_sources = self._extract_gallery_image_sources(info)
        if image_sources:
            return SourceMediaArtifact(
                source_type=self._platform,
                canonical_url=canonical_url,
                media_kind="gallery" if len(image_sources) > 1 else "photo",
                source_id=source_id,
                title=title,
                uploader=uploader,
                thumbnail_url=thumbnail_url,
                duration_sec=duration_sec,
                image_sources=image_sources,
            )

        if _is_audio_only(info):
            return SourceMediaArtifact(
                source_type=self._platform,
                canonical_url=canonical_url,
                media_kind="audio",
                source_id=source_id,
                title=title,
                uploader=uploader,
                thumbnail_url=thumbnail_url,
                duration_sec=duration_sec,
            )

        if _is_image_only(info):
            direct_image = _extract_direct_image_source(info)
            if not direct_image:
                return None
            return SourceMediaArtifact(
                source_type=self._platform,
                canonical_url=canonical_url,
                media_kind="photo",
                source_id=source_id,
                title=title,
                uploader=uploader,
                thumbnail_url=thumbnail_url,
                duration_sec=duration_sec,
                image_sources=(direct_image,),
            )

        if _looks_like_video(info):
            return SourceMediaArtifact(
                source_type=self._platform,
                canonical_url=canonical_url,
                media_kind="video",
                source_id=source_id,
                title=title,
                uploader=uploader,
                thumbnail_url=thumbnail_url,
                duration_sec=duration_sec,
            )
        return None

    async def _download_gallery_entry(
        self,
        entry_url: str,
        *,
        work_dir: Path,
        normalized_key: str,
        file_stem: str,
    ) -> Path:
        if _looks_like_direct_image_url(entry_url):
            suffix = Path(urlparse(entry_url).path).suffix or ".jpg"
            destination = work_dir / f"{file_stem}{suffix}"
            await self._download_binary(entry_url, destination)
            return destination

        path, _ = await self._downloader.download_url(
            entry_url,
            work_dir,
            normalized_key=normalized_key,
            format_selector=None,
            merge_output_format=None,
        )
        return path

    async def _download_binary(self, url: str, destination: Path) -> None:
        try:
            async with httpx.AsyncClient(timeout=self._request_timeout_seconds, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DownloadError("Failed to download media binary.", temporary=True, context={"url": url}) from exc
        destination.write_bytes(response.content)

    @staticmethod
    def _extract_gallery_image_sources(info: dict[str, object]) -> tuple[str, ...]:
        entries = info.get("entries")
        if not isinstance(entries, list):
            return ()
        sources: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            direct_image = _extract_direct_image_source(entry)
            if direct_image:
                sources.append(direct_image)
                continue
            entry_url = _canonical_url(entry, "")
            if entry_url:
                sources.append(entry_url)
        deduped: list[str] = []
        seen: set[str] = set()
        for source in sources:
            if source in seen:
                continue
            seen.add(source)
            deduped.append(source)
        return tuple(deduped)


def _artifact_to_resource_type(media_kind: str) -> str:
    if media_kind in {"photo", "gallery"}:
        return "photo_post"
    if media_kind == "audio":
        return "music_only"
    return "video"


def _clean_optional(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned or None


def _to_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _canonical_url(info: dict[str, object], fallback_url: str) -> str:
    for key in ("webpage_url", "original_url", "url"):
        value = info.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    return fallback_url


def _fallback_source_id(canonical_url: str) -> str:
    path = Path(urlparse(canonical_url).path)
    if path.stem:
        return path.stem
    return canonical_url.rstrip("/").rsplit("/", 1)[-1] or "resource"


def _extract_thumbnail(info: dict[str, object]) -> str | None:
    thumbnail = info.get("thumbnail")
    if isinstance(thumbnail, str) and thumbnail.startswith("http"):
        return thumbnail
    thumbnails = info.get("thumbnails")
    if isinstance(thumbnails, list):
        for item in thumbnails:
            if isinstance(item, dict):
                url = item.get("url")
                if isinstance(url, str) and url.startswith("http"):
                    return url
    return None


def _extension_from_info(info: dict[str, object]) -> str:
    ext = info.get("ext")
    if isinstance(ext, str):
        return ext.casefold()
    return ""


def _extract_direct_image_source(info: dict[str, object]) -> str | None:
    url = info.get("url")
    if isinstance(url, str) and url.startswith("http") and _looks_like_direct_image_url(url):
        return url
    webpage_url = info.get("webpage_url")
    if isinstance(webpage_url, str) and webpage_url.startswith("http") and _looks_like_direct_image_url(webpage_url):
        return webpage_url
    thumbnails = info.get("thumbnails")
    if isinstance(thumbnails, list):
        for item in thumbnails:
            if isinstance(item, dict):
                candidate = item.get("url")
                if isinstance(candidate, str) and candidate.startswith("http") and _looks_like_direct_image_url(candidate):
                    return candidate
    return None


def _is_audio_only(info: dict[str, object]) -> bool:
    ext = _extension_from_info(info)
    if ext in _AUDIO_EXTENSIONS:
        return True
    return info.get("vcodec") in {None, "none"} and info.get("acodec") not in {None, "none"}


def _is_image_only(info: dict[str, object]) -> bool:
    ext = _extension_from_info(info)
    if ext in _IMAGE_EXTENSIONS:
        return True
    direct_url = info.get("url")
    return isinstance(direct_url, str) and _looks_like_direct_image_url(direct_url)


def _looks_like_video(info: dict[str, object]) -> bool:
    ext = _extension_from_info(info)
    if ext and ext not in _IMAGE_EXTENSIONS and ext not in _AUDIO_EXTENSIONS:
        return True
    return info.get("vcodec") not in {None, "none"}


def _looks_like_direct_image_url(url: str) -> bool:
    suffix = Path(urlparse(url).path).suffix.lower().lstrip(".")
    return suffix in _IMAGE_EXTENSIONS


def _is_image_path(path: Path) -> bool:
    return path.suffix.lower().lstrip(".") in _IMAGE_EXTENSIONS
