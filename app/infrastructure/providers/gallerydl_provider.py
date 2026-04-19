from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.domain.entities.media_result import MediaMetadata
from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.entities.source_media_artifact import SourceMediaArtifact
from app.domain.enums.platform import Platform
from app.domain.errors import DownloadError, NormalizationError, UnsupportedUrlError
from app.domain.policies import build_cache_key
from app.infrastructure.downloaders.gallerydl_client import GalleryDlClient
from app.infrastructure.logging import get_logger, log_event
from app.infrastructure.providers.gallery_utils import build_artifact_from_gallery_probe
from app.infrastructure.providers.source_detection import detect_source_type, extract_first_supported_url


@dataclass(slots=True)
class _PreparedBundle:
    work_dir: Path
    image_files: tuple[Path, ...]
    audio_files: tuple[Path, ...]
    video_files: tuple[Path, ...]


class GalleryDlUrlProvider:
    def __init__(
        self,
        *,
        platform: Platform,
        downloader: GalleryDlClient,
        request_timeout_seconds: int,
    ) -> None:
        self.platform_name = platform.value
        self._platform = platform
        self._downloader = downloader
        self._request_timeout_seconds = request_timeout_seconds
        self._logger = get_logger(__name__)
        self._bundles: dict[str, _PreparedBundle] = {}

    def extract_first_url(self, text: str) -> str | None:
        return extract_first_supported_url(text, self._platform)

    def can_handle(self, url: str) -> bool:
        return detect_source_type(url) == self._platform

    async def normalize(self, url: str) -> NormalizedResource:
        if not self.can_handle(url):
            raise UnsupportedUrlError()

        probe_entries = await self._downloader.probe_url(url)
        artifact = self._build_artifact(url, probe_entries)
        if artifact is None:
            raise NormalizationError("gallery-dl did not expose a supported media result.", context={"url": url})

        resource_type = _artifact_to_resource_type(artifact.media_kind)
        normalized = NormalizedResource(
            platform=self._platform,
            resource_type=resource_type,
            resource_id=artifact.source_id,
            normalized_key=build_cache_key(self._platform, resource_type, artifact.source_id),
            original_url=url,
            canonical_url=artifact.canonical_url,
            engine_name="gallery-dl",
            media_kind=artifact.media_kind,
            title=artifact.title,
            author=artifact.uploader,
            audio_url=artifact.audio_source,
            image_urls=artifact.image_sources,
            image_entries=artifact.image_entries,
            thumbnail_url=artifact.thumbnail_url,
            duration_sec=artifact.duration_sec,
            has_expected_audio=artifact.has_expected_audio,
        )
        if normalized.resource_type == "photo_post":
            log_event(
                self._logger,
                20,
                "media_gallery_detected",
                normalized_key=normalized.normalized_key,
                source_type=self._platform.value,
                entry_count=normalized.entry_count,
            )
            log_event(
                self._logger,
                20,
                "gallery_artifact_built" if normalized.entry_count > 1 else "visual_artifact_built",
                normalized_key=normalized.normalized_key,
                source_type=self._platform.value,
                canonical_url=normalized.canonical_url,
                image_count=normalized.entry_count,
                has_expected_audio=normalized.has_expected_audio,
            )
        log_event(
            self._logger,
            20,
            "normalization_completed",
            normalized_key=normalized.normalized_key,
            source_type=self._platform.value,
            canonical_url=normalized.canonical_url,
            media_kind=normalized.media_kind,
            engine_name=normalized.engine_name,
        )
        return normalized

    async def fetch_metadata(self, normalized: NormalizedResource) -> MediaMetadata:
        return MediaMetadata(
            title=normalized.title,
            duration_sec=normalized.duration_sec,
            author=normalized.author,
            description=None,
            size_bytes=None,
            has_audio=normalized.has_expected_audio
            if normalized.has_expected_audio is not None
            else (True if normalized.resource_type == "music_only" else (False if normalized.resource_type == "photo_post" else None)),
        )

    async def download_video(self, normalized: NormalizedResource, work_dir: Path) -> Path:
        bundle = await self._ensure_bundle(normalized, work_dir)
        if not bundle.video_files:
            raise DownloadError(
                "gallery-dl did not download a video file.",
                temporary=False,
                context={"normalized_key": normalized.normalized_key},
            )
        return bundle.video_files[0]

    async def download_audio(self, normalized: NormalizedResource, work_dir: Path) -> Path | None:
        bundle = await self._ensure_bundle(normalized, work_dir)
        if bundle.audio_files:
            return bundle.audio_files[0]
        return None

    async def download_image_entry(
        self,
        normalized: NormalizedResource,
        work_dir: Path,
        *,
        source_url: str,
        entry_index: int,
    ) -> Path:
        del source_url
        bundle = await self._ensure_bundle(normalized, work_dir)
        if entry_index < 1 or entry_index > len(bundle.image_files):
            raise DownloadError(
                "Requested gallery entry is unavailable.",
                temporary=False,
                context={"normalized_key": normalized.normalized_key, "entry_index": entry_index},
            )
        return bundle.image_files[entry_index - 1]

    async def download_images(self, normalized: NormalizedResource, work_dir: Path) -> tuple[Path, ...]:
        bundle = await self._ensure_bundle(normalized, work_dir)
        if not bundle.image_files:
            raise DownloadError(
                "gallery-dl did not download image files.",
                temporary=False,
                context={"normalized_key": normalized.normalized_key},
            )
        return bundle.image_files

    def _build_artifact(
        self,
        original_url: str,
        probe_entries: tuple[dict[str, object], ...],
    ) -> SourceMediaArtifact | None:
        return build_artifact_from_gallery_probe(
            platform=self._platform,
            original_url=original_url,
            probe_entries=probe_entries,
        )

    async def _ensure_bundle(self, normalized: NormalizedResource, work_dir: Path) -> _PreparedBundle:
        existing = self._bundles.get(normalized.normalized_key)
        if existing is not None and existing.work_dir == work_dir and all(path.exists() for path in (*existing.image_files, *existing.audio_files, *existing.video_files)):
            return existing

        log_event(
            self._logger,
            20,
            "media_download_started",
            normalized_key=normalized.normalized_key,
            source_type=self._platform.value,
            canonical_url=normalized.canonical_url,
            media_kind=normalized.media_kind,
            engine_name="gallery-dl",
        )
        collection = await self._downloader.download_collection(normalized.canonical_url, work_dir)
        bundle = _PreparedBundle(
            work_dir=work_dir,
            image_files=collection.image_files,
            audio_files=collection.audio_files,
            video_files=collection.video_files,
        )
        self._bundles[normalized.normalized_key] = bundle
        log_event(
            self._logger,
            20,
            "media_download_finished",
            normalized_key=normalized.normalized_key,
            source_type=self._platform.value,
            canonical_url=normalized.canonical_url,
            media_kind=normalized.media_kind,
            engine_name="gallery-dl",
            image_count=len(bundle.image_files),
            audio_count=len(bundle.audio_files),
            video_count=len(bundle.video_files),
        )
        return bundle


def _artifact_to_resource_type(media_kind: str) -> str:
    if media_kind in {"photo", "gallery"}:
        return "photo_post"
    if media_kind == "audio":
        return "music_only"
    return "video"
