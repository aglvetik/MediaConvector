from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.domain.entities.media_result import MediaMetadata
from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.entities.source_media_artifact import SourceMediaArtifact
from app.domain.entities.visual_media_entry import VisualMediaEntry
from app.domain.enums.platform import Platform
from app.domain.enums.tiktok_resource_type import TikTokResourceType
from app.domain.errors import DownloadError, NormalizationError, UnsupportedUrlError
from app.domain.policies import build_cache_key
from app.infrastructure.downloaders import GalleryDlClient, YtDlpClient
from app.infrastructure.logging import get_logger, log_event
from app.infrastructure.providers.gallery_utils import build_artifact_from_gallery_probe
from app.infrastructure.providers.tiktok.url_utils import (
    extract_first_tiktok_url,
    extract_music_id,
    extract_photo_id,
    extract_video_id,
    is_tiktok_host,
    sanitize_url,
)

_WEB_JSON_PATTERNS = (
    re.compile(
        r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(?P<payload>.+?)</script>',
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r'<script[^>]+id="SIGI_STATE"[^>]*>(?P<payload>.+?)</script>',
        re.IGNORECASE | re.DOTALL,
    ),
)
_IMAGE_URL_PATTERN = re.compile(r"https?://[^\s\"']+\.(?:jpg|jpeg|png|webp)(?:[^\s\"']*)", re.IGNORECASE)
_AUDIO_URL_PATTERN = re.compile(r"https?://[^\s\"']+tiktokcdn\.com[^\s\"']+(?:\.mp3|\.m4a)?[^\s\"']*", re.IGNORECASE)
_TIKTOK_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://www.tiktok.com/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass(slots=True, frozen=True)
class _TikTokImageSelection:
    url: str
    source_field: str
    fallback_fields_considered: bool


@dataclass(slots=True)
class _PreparedGalleryBundle:
    work_dir: Path
    image_files: tuple[Path, ...]
    audio_files: tuple[Path, ...]
    video_files: tuple[Path, ...]


class TikTokProvider:
    platform_name = Platform.TIKTOK.value

    def __init__(
        self,
        *,
        downloader: YtDlpClient,
        request_timeout_seconds: int,
        gallery_downloader: GalleryDlClient | None = None,
    ) -> None:
        self._downloader = downloader
        self._request_timeout_seconds = request_timeout_seconds
        self._gallery_downloader = gallery_downloader
        self._gallery_bundles: dict[str, _PreparedGalleryBundle] = {}
        self._logger = get_logger(__name__)

    def extract_first_url(self, text: str) -> str | None:
        return extract_first_tiktok_url(text)

    def can_handle(self, url: str) -> bool:
        return is_tiktok_host(url)

    async def normalize(self, url: str) -> NormalizedResource:
        if not self.can_handle(url):
            raise UnsupportedUrlError()

        original_url = url
        expanded_url: str | None = None
        cleaned_url: str | None = None
        try:
            expanded_url = await self._resolve_short_url(url)
            if expanded_url != original_url:
                log_event(
                    self._logger,
                    20,
                    "tiktok_url_expanded",
                    original_url=original_url,
                    expanded_url=expanded_url,
                )

            cleaned_url = sanitize_url(expanded_url)
            if cleaned_url != expanded_url:
                log_event(
                    self._logger,
                    20,
                    "tiktok_url_cleaned",
                    original_url=original_url,
                    expanded_url=expanded_url,
                    cleaned_url=cleaned_url,
                )

            info: dict[str, object] = {}
            try:
                info = await self._downloader.probe_url(cleaned_url)
            except DownloadError as exc:
                log_event(
                    self._logger,
                    30,
                    "tiktok_probe_failed",
                    original_url=original_url,
                    expanded_url=expanded_url,
                    cleaned_url=cleaned_url,
                    reason=str(exc),
                )
                info = {}

            resource_type = self._resolve_resource_type(cleaned_url, info)
            resource_id = self._resolve_resource_id(cleaned_url, info, resource_type)
            canonical_url = cleaned_url
            if not resource_id:
                canonical_url = sanitize_url(str(info.get("webpage_url") or cleaned_url))
                resource_type = self._resolve_resource_type(canonical_url, info)
                resource_id = self._resolve_resource_id(canonical_url, info, resource_type)
            if not resource_id:
                raise NormalizationError(
                    "Could not extract TikTok resource id.",
                    context={"url": original_url, "expanded_url": expanded_url, "cleaned_url": canonical_url},
                )

            web_state = await self._load_web_state(canonical_url)
            image_selections = tuple(self._extract_image_selections(info, web_state))
            image_urls = tuple(selection.url for selection in image_selections)
            audio_url = self._extract_audio_url(info, web_state)
            video_url = self._extract_video_url(info)
            thumbnail_url = self._extract_thumbnail_url(info, web_state)
            title = self._extract_title(info, web_state)
            author = self._extract_author(info, web_state)
            duration_sec = self._extract_duration(info, web_state)
            gallery_artifact = await self._build_gallery_artifact(
                canonical_url=canonical_url,
                resource_id=resource_id,
                title=title,
                author=author,
                duration_sec=duration_sec,
            )
            if gallery_artifact is not None and resource_type == TikTokResourceType.PHOTO_POST:
                image_urls = gallery_artifact.image_sources
                audio_url = audio_url or gallery_artifact.audio_source
                duration_sec = duration_sec or gallery_artifact.duration_sec
                title = title or gallery_artifact.title
                author = author or gallery_artifact.uploader

            allow_download_first_gallery = resource_type == TikTokResourceType.PHOTO_POST and self._gallery_downloader is not None
            if resource_type == TikTokResourceType.PHOTO_POST and not image_urls and not allow_download_first_gallery:
                raise NormalizationError(
                    "Photo post did not expose any images.",
                    context={"url": original_url, "expanded_url": expanded_url, "cleaned_url": canonical_url},
                )
            if resource_type == TikTokResourceType.MUSIC_ONLY and audio_url is None:
                raise NormalizationError(
                    "TikTok music link did not expose an audio URL.",
                    context={"url": original_url, "expanded_url": expanded_url, "cleaned_url": canonical_url},
                )

            normalized = NormalizedResource(
                platform=Platform.TIKTOK,
                resource_type=resource_type.value,
                resource_id=resource_id,
                normalized_key=build_cache_key(Platform.TIKTOK, resource_type.value, resource_id),
                original_url=original_url,
                canonical_url=canonical_url,
                engine_name="gallery-dl" if resource_type == TikTokResourceType.PHOTO_POST and self._gallery_downloader is not None else "yt-dlp",
                media_kind=gallery_artifact.media_kind
                if gallery_artifact is not None
                else ("gallery" if resource_type == TikTokResourceType.PHOTO_POST and not image_urls else self._resolve_media_kind(resource_type, image_urls)),
                title=title,
                author=author,
                video_url=video_url,
                audio_url=audio_url,
                image_urls=image_urls,
                image_entries=gallery_artifact.image_entries
                if gallery_artifact is not None
                else tuple(
                    VisualMediaEntry(
                        source_url=image_url,
                        order=index,
                        mime_type_hint=f"image/{'jpeg' if self._guess_extension(image_url, default='jpg') == 'jpg' else self._guess_extension(image_url, default='jpg')}",
                    )
                    for index, image_url in enumerate(image_urls, start=1)
                ),
                thumbnail_url=thumbnail_url,
                duration_sec=duration_sec,
                has_expected_audio=(
                    audio_url is not None
                    if resource_type != TikTokResourceType.VIDEO and not (resource_type == TikTokResourceType.PHOTO_POST and self._gallery_downloader is not None and gallery_artifact is None)
                    else None
                ),
            )
        except httpx.HTTPError as exc:
            log_event(
                self._logger,
                40,
                "tiktok_normalization_failed",
                original_url=original_url,
                expanded_url=expanded_url,
                cleaned_url=cleaned_url,
                reason=str(exc),
            )
            raise NormalizationError(
                "Failed to resolve TikTok short URL.",
                context={"url": original_url, "expanded_url": expanded_url, "cleaned_url": cleaned_url},
            ) from exc
        except (NormalizationError, UnsupportedUrlError) as exc:
            log_event(
                self._logger,
                40,
                "tiktok_normalization_failed",
                original_url=original_url,
                expanded_url=expanded_url,
                cleaned_url=cleaned_url,
                reason=str(exc),
            )
            raise

        log_event(
            self._logger,
            20,
            "tiktok_url_normalized",
            original_url=original_url,
            expanded_url=expanded_url,
            cleaned_url=cleaned_url,
            canonical_url=normalized.canonical_url,
            resource_type=normalized.resource_type,
            normalized_key=normalized.normalized_key,
        )
        log_event(
            self._logger,
            20,
            "tiktok_resource_resolved",
            normalized_key=normalized.normalized_key,
            resource_type=normalized.resource_type,
            canonical_url=normalized.canonical_url,
            engine_name=normalized.engine_name,
        )
        if resource_type == TikTokResourceType.PHOTO_POST:
            log_event(self._logger, 20, "tiktok_photo_post_detected", normalized_key=normalized.normalized_key)
            for index, selection in enumerate(image_selections, start=1):
                log_event(
                    self._logger,
                    10,
                    "tiktok_photo_image_url_selected",
                    normalized_key=normalized.normalized_key,
                    canonical_url=normalized.canonical_url,
                    image_index=index,
                    image_source_field=selection.source_field,
                    image_host=(urlparse(selection.url).hostname or "").lower(),
                    fallback_fields_considered=selection.fallback_fields_considered,
                )
            log_event(
                self._logger,
                20,
                "gallery_artifact_built" if len(image_urls) > 1 else "visual_artifact_built",
                normalized_key=normalized.normalized_key,
                source_type=Platform.TIKTOK.value,
                canonical_url=normalized.canonical_url,
                image_count=len(image_urls),
                has_expected_audio=normalized.has_expected_audio,
            )
        elif resource_type == TikTokResourceType.MUSIC_ONLY:
            log_event(self._logger, 20, "tiktok_music_link_detected", normalized_key=normalized.normalized_key)
        else:
            log_event(self._logger, 20, "normalization_completed", normalized_key=normalized.normalized_key, canonical_url=normalized.canonical_url)
        return normalized

    async def fetch_metadata(self, normalized: NormalizedResource) -> MediaMetadata:
        if normalized.resource_type == TikTokResourceType.MUSIC_ONLY.value:
            return MediaMetadata(
                title=normalized.title,
                duration_sec=normalized.duration_sec,
                author=normalized.author,
                description=None,
                size_bytes=None,
                has_audio=True,
            )
        if normalized.resource_type == TikTokResourceType.PHOTO_POST.value:
            return MediaMetadata(
                title=normalized.title,
                duration_sec=normalized.duration_sec,
                author=normalized.author,
                description=None,
                size_bytes=None,
                has_audio=normalized.has_expected_audio,
            )
        return await self._downloader.fetch_metadata(normalized)

    async def download_video(self, normalized: NormalizedResource, work_dir: Path) -> Path:
        path, _ = await self._downloader.download_video(normalized, work_dir)
        return path

    async def download_audio(self, normalized: NormalizedResource, work_dir: Path) -> Path | None:
        if normalized.resource_type == TikTokResourceType.PHOTO_POST.value and normalized.engine_name == "gallery-dl":
            bundle = await self._ensure_gallery_bundle(normalized, work_dir)
            if bundle.audio_files:
                return bundle.audio_files[0]
            return None
        if normalized.audio_url is None:
            return None
        extension = self._guess_extension(normalized.audio_url, default="m4a")
        audio_path = work_dir / f"{normalized.resource_id}-audio.{extension}"
        await self._download_binary(normalized.audio_url, audio_path)
        return audio_path

    async def download_image_entry(
        self,
        normalized: NormalizedResource,
        work_dir: Path,
        *,
        source_url: str,
        entry_index: int,
    ) -> Path:
        if normalized.resource_type == TikTokResourceType.PHOTO_POST.value and normalized.engine_name == "gallery-dl":
            bundle = await self._ensure_gallery_bundle(normalized, work_dir)
            if entry_index < 1 or entry_index > len(bundle.image_files):
                raise DownloadError(
                    "Requested gallery entry is unavailable.",
                    temporary=False,
                    context={"normalized_key": normalized.normalized_key, "entry_index": entry_index},
                )
            return bundle.image_files[entry_index - 1]
        normalized_url = self._normalize_image_url(source_url)
        image_path = work_dir / f"{normalized.resource_id}-photo-{entry_index}.{self._guess_extension(normalized_url, default='jpg')}"
        await self._download_binary(
            normalized_url,
            image_path,
            original_url=source_url,
            headers=self._asset_headers(normalized_url),
            allow_https_retry=True,
        )
        return image_path

    async def download_images(self, normalized: NormalizedResource, work_dir: Path) -> tuple[Path, ...]:
        if normalized.resource_type == TikTokResourceType.PHOTO_POST.value and normalized.engine_name == "gallery-dl":
            bundle = await self._ensure_gallery_bundle(normalized, work_dir)
            if not bundle.image_files:
                raise DownloadError(
                    "gallery-dl did not download image files.",
                    temporary=False,
                    context={"normalized_key": normalized.normalized_key},
                )
            return bundle.image_files
        paths: list[Path] = []
        for index, image_url in enumerate(normalized.image_urls, start=1):
            image_path = await self.download_image_entry(
                normalized,
                work_dir,
                source_url=image_url,
                entry_index=index,
            )
            paths.append(image_path)
        return tuple(paths)

    async def download_with_metadata(self, normalized: NormalizedResource, work_dir: Path) -> tuple[Path, MediaMetadata]:
        return await self._downloader.download_video(normalized, work_dir)

    async def _build_gallery_artifact(
        self,
        *,
        canonical_url: str,
        resource_id: str,
        title: str | None,
        author: str | None,
        duration_sec: int | None,
    ) -> SourceMediaArtifact | None:
        if self._gallery_downloader is None:
            return None
        try:
            probe_entries = await self._gallery_downloader.probe_url(canonical_url)
        except DownloadError as exc:
            log_event(
                self._logger,
                30,
                "gallery_probe_failed",
                canonical_url=canonical_url,
                source_type=Platform.TIKTOK.value,
                error_code=exc.error_code,
            )
            return None
        artifact = build_artifact_from_gallery_probe(
            platform=Platform.TIKTOK,
            original_url=canonical_url,
            canonical_url=canonical_url,
            source_id=resource_id,
            probe_entries=probe_entries,
            fallback_title=title,
            fallback_uploader=author,
        )
        if artifact is not None and artifact.media_kind not in {"photo", "gallery"}:
            return None
        return artifact

    async def _ensure_gallery_bundle(self, normalized: NormalizedResource, work_dir: Path) -> _PreparedGalleryBundle:
        if self._gallery_downloader is None:
            raise DownloadError(
                "gallery-dl is not configured for TikTok photo posts.",
                temporary=False,
                context={"normalized_key": normalized.normalized_key},
            )
        existing = self._gallery_bundles.get(normalized.normalized_key)
        if existing is not None and existing.work_dir == work_dir and all(path.exists() for path in (*existing.image_files, *existing.audio_files, *existing.video_files)):
            return existing

        log_event(
            self._logger,
            20,
            "gallery_download_started",
            normalized_key=normalized.normalized_key,
            source_type=Platform.TIKTOK.value,
            canonical_url=normalized.canonical_url,
            media_kind=normalized.media_kind,
            engine_name="gallery-dl",
        )
        collection = await self._gallery_downloader.download_collection(normalized.canonical_url, work_dir)
        log_event(
            self._logger,
            20,
            "gallery_files_collected",
            normalized_key=normalized.normalized_key,
            source_type=Platform.TIKTOK.value,
            canonical_url=normalized.canonical_url,
            file_count=len(collection.all_files),
            image_count=len(collection.image_files),
            audio_count=len(collection.audio_files),
            video_count=len(collection.video_files),
        )
        bundle = _PreparedGalleryBundle(
            work_dir=work_dir,
            image_files=collection.image_files,
            audio_files=collection.audio_files,
            video_files=collection.video_files,
        )
        self._gallery_bundles[normalized.normalized_key] = bundle
        log_event(
            self._logger,
            20,
            "gallery_download_finished",
            normalized_key=normalized.normalized_key,
            source_type=Platform.TIKTOK.value,
            canonical_url=normalized.canonical_url,
            media_kind=normalized.media_kind,
            engine_name="gallery-dl",
            image_count=len(bundle.image_files),
            audio_count=len(bundle.audio_files),
            video_count=len(bundle.video_files),
        )
        return bundle

    async def _resolve_short_url(self, url: str) -> str:
        host = (urlparse(url).hostname or "").lower()
        if host not in {"vm.tiktok.com", "vt.tiktok.com"}:
            return url
        async with httpx.AsyncClient(follow_redirects=True, timeout=self._request_timeout_seconds) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                    )
                },
            )
            response.raise_for_status()
            return str(response.url)

    async def _load_web_state(self, url: str) -> dict[str, object]:
        try:
            async with httpx.AsyncClient(timeout=self._request_timeout_seconds, follow_redirects=True) as client:
                response = await client.get(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                        )
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError:
            return {}

        html = response.text
        for pattern in _WEB_JSON_PATTERNS:
            match = pattern.search(html)
            if not match:
                continue
            payload = match.group("payload")
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                continue
        return {}

    async def _download_binary(
        self,
        url: str,
        destination: Path,
        *,
        original_url: str | None = None,
        headers: dict[str, str] | None = None,
        allow_https_retry: bool = False,
    ) -> None:
        normalized_url = url
        attempted_https_upgrade = (
            (original_url or url).startswith("http://") and normalized_url.startswith("https://")
        )
        attempt_plan = [normalized_url]
        if allow_https_retry and normalized_url.startswith("http://"):
            secure_url = "https://" + normalized_url.removeprefix("http://")
            if secure_url != normalized_url:
                attempt_plan.append(secure_url)

        last_error: DownloadError | None = None
        for index, candidate_url in enumerate(attempt_plan):
            attempted_https_upgrade = attempted_https_upgrade or index > 0
            try:
                async with httpx.AsyncClient(timeout=self._request_timeout_seconds, follow_redirects=True) as client:
                    response = await client.get(candidate_url, headers=headers or self._default_headers())
                    response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                last_error = DownloadError(
                    "Failed to fetch TikTok binary asset.",
                    context={
                        "url": candidate_url,
                        "original_url": original_url or url,
                        "normalized_url": candidate_url,
                        "https_upgrade_attempted": attempted_https_upgrade,
                        "status_code": exc.response.status_code,
                        "exception": str(exc),
                    },
                )
                continue
            except httpx.HTTPError as exc:
                last_error = DownloadError(
                    "Failed to fetch TikTok binary asset.",
                    context={
                        "url": candidate_url,
                        "original_url": original_url or url,
                        "normalized_url": candidate_url,
                        "https_upgrade_attempted": attempted_https_upgrade,
                        "exception": str(exc),
                    },
                )
                continue
            destination.write_bytes(response.content)
            return

        if last_error is not None:
            raise last_error
        raise DownloadError(
            "Failed to fetch TikTok binary asset.",
            context={
                "url": normalized_url,
                "original_url": original_url or url,
                "normalized_url": normalized_url,
                "https_upgrade_attempted": attempted_https_upgrade,
            },
        )

    def _resolve_resource_type(self, canonical_url: str, info: dict[str, object]) -> TikTokResourceType:
        path = urlparse(canonical_url).path.lower()
        if "/music/" in path:
            return TikTokResourceType.MUSIC_ONLY
        if "/photo/" in path:
            return TikTokResourceType.PHOTO_POST
        if self._looks_like_photo_post(info):
            return TikTokResourceType.PHOTO_POST
        if self._looks_like_music_only(info):
            return TikTokResourceType.MUSIC_ONLY
        return TikTokResourceType.VIDEO

    @staticmethod
    def _resolve_media_kind(resource_type: TikTokResourceType, image_urls: tuple[str, ...]) -> str:
        if resource_type == TikTokResourceType.MUSIC_ONLY:
            return "audio"
        if resource_type == TikTokResourceType.PHOTO_POST:
            return "gallery" if len(image_urls) > 1 else "photo"
        return "video"

    @staticmethod
    def _resolve_resource_id(canonical_url: str, info: dict[str, object], resource_type: TikTokResourceType) -> str:
        if resource_type == TikTokResourceType.PHOTO_POST:
            return extract_photo_id(canonical_url) or str(info.get("id") or "")
        if resource_type == TikTokResourceType.MUSIC_ONLY:
            return extract_music_id(canonical_url) or str(info.get("id") or "")
        return extract_video_id(canonical_url) or str(info.get("id") or "")

    @staticmethod
    def _looks_like_photo_post(info: dict[str, object]) -> bool:
        entries = info.get("entries")
        if isinstance(entries, list) and entries:
            return True
        formats = info.get("formats")
        if not isinstance(formats, list):
            return False
        if not formats:
            return False
        has_real_video = any(
            isinstance(item, dict) and item.get("vcodec") not in {None, "none"} and (item.get("width") or item.get("height"))
            for item in formats
        )
        return not has_real_video and any(isinstance(item, dict) and "music" in str(item.get("url") or "") for item in formats)

    @staticmethod
    def _looks_like_music_only(info: dict[str, object]) -> bool:
        formats = info.get("formats")
        if isinstance(formats, list) and formats:
            return all(isinstance(item, dict) and item.get("vcodec") in {None, "none"} for item in formats)
        return False

    def _extract_image_selections(
        self,
        info: dict[str, object],
        web_state: dict[str, object],
    ) -> list[_TikTokImageSelection]:
        candidate_sets: list[list[_TikTokImageSelection]] = []
        selections = self._extract_image_selections_from_entries(
            info.get("entries"),
            base_path="info.entries",
            allow_fallback_fields=False,
        )
        if selections:
            candidate_sets.append(self._dedupe_image_selections(selections))
        for group_path, image_items in self._find_structured_image_groups(web_state):
            selections = self._extract_image_selections_from_entries(
                image_items,
                base_path=group_path,
                allow_fallback_fields=False,
            )
            if selections:
                candidate_sets.append(self._dedupe_image_selections(selections))

        if candidate_sets:
            return max(candidate_sets, key=self._score_image_selection_set)

        selections = self._extract_image_selections_from_entries(
            info.get("entries"),
            base_path="info.entries",
            allow_fallback_fields=True,
        )
        if selections:
            candidate_sets.append(self._dedupe_image_selections(selections))

        for group_path, image_items in self._find_structured_image_groups(web_state):
            selections = self._extract_image_selections_from_entries(
                image_items,
                base_path=group_path,
                allow_fallback_fields=True,
            )
            if selections:
                candidate_sets.append(self._dedupe_image_selections(selections))

        if candidate_sets:
            return max(candidate_sets, key=self._score_image_selection_set)

        fallback_urls = [
            self._normalize_image_url(url)
            for url in self._find_image_urls_in_mapping(web_state)
            if not self._is_broken_tiktok_image_host(urlparse(url).hostname or "")
        ]
        deduped_fallback_urls = self._dedupe_urls(fallback_urls)
        return [
            _TikTokImageSelection(
                url=url,
                source_field="web_state.regex_image_url_fallback",
                fallback_fields_considered=True,
            )
            for url in deduped_fallback_urls
        ]

    def _extract_image_selections_from_entries(
        self,
        payload: object,
        *,
        base_path: str,
        allow_fallback_fields: bool,
    ) -> list[_TikTokImageSelection]:
        if not isinstance(payload, list):
            return []

        selections: list[_TikTokImageSelection] = []
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                continue
            selection = self._select_image_entry_url(
                item,
                base_path=f"{base_path}[{index}]",
                allow_fallback_fields=allow_fallback_fields,
            )
            if selection is None:
                continue
            selections.append(selection)
        return selections

    def _select_image_entry_url(
        self,
        item: dict[str, object],
        *,
        base_path: str,
        allow_fallback_fields: bool,
    ) -> _TikTokImageSelection | None:
        candidate_specs: list[tuple[str, tuple[str, ...]]] = [
            ("image_url.url_list", ("image_url", "url_list")),
            ("image_url.urlList", ("image_url", "urlList")),
            ("imageURL.urlList", ("imageURL", "urlList")),
            ("imageURL.url_list", ("imageURL", "url_list")),
            ("imageUrl.urlList", ("imageUrl", "urlList")),
            ("imageUrl.url_list", ("imageUrl", "url_list")),
            ("display_image.url_list", ("display_image", "url_list")),
            ("display_image.urlList", ("display_image", "urlList")),
            ("displayImage.urlList", ("displayImage", "urlList")),
            ("displayImage.url_list", ("displayImage", "url_list")),
            ("image.url_list", ("image", "url_list")),
            ("image.urlList", ("image", "urlList")),
            ("display_image", ("display_image",)),
            ("displayImage", ("displayImage",)),
            ("image", ("image",)),
            ("imageURL", ("imageURL",)),
            ("thumbnails", ("thumbnails",)),
        ]
        if allow_fallback_fields:
            candidate_specs.extend(
                [
                    ("display_url", ("display_url",)),
                    ("url", ("url",)),
                ]
            )

        for source_field, path in candidate_specs:
            urls = self._extract_urls_from_path(item, path)
            candidate = self._choose_preferred_image_url(urls)
            if candidate is None:
                continue
            return _TikTokImageSelection(
                url=candidate,
                source_field=f"{base_path}.{source_field}",
                fallback_fields_considered=allow_fallback_fields,
            )
        return None

    def _find_structured_image_groups(self, payload: object, *, path: str = "web_state") -> list[tuple[str, list[dict[str, object]]]]:
        groups: list[tuple[str, list[dict[str, object]]]] = []
        if isinstance(payload, dict):
            image_post = payload.get("imagePost")
            if isinstance(image_post, dict):
                images = image_post.get("images")
                if self._is_structured_image_list(images):
                    groups.append((f"{path}.imagePost.images", images))
            image_post_info = payload.get("image_post_info")
            if isinstance(image_post_info, dict):
                images = image_post_info.get("images")
                if self._is_structured_image_list(images):
                    groups.append((f"{path}.image_post_info.images", images))
            images = payload.get("images")
            if self._is_structured_image_list(images):
                groups.append((f"{path}.images", images))
            for key, value in payload.items():
                groups.extend(self._find_structured_image_groups(value, path=f"{path}.{key}"))
        elif isinstance(payload, list):
            for index, item in enumerate(payload):
                groups.extend(self._find_structured_image_groups(item, path=f"{path}[{index}]"))
        return groups

    @staticmethod
    def _is_structured_image_list(payload: object) -> bool:
        return (
            isinstance(payload, list)
            and bool(payload)
            and all(isinstance(item, dict) for item in payload)
            and any(
                any(key in item for key in ("image_url", "imageURL", "imageUrl", "display_image", "displayImage", "image", "thumbnails", "url"))
                for item in payload
            )
        )

    def _extract_urls_from_path(self, payload: dict[str, object], path: tuple[str, ...]) -> tuple[str, ...]:
        current: object = payload
        for part in path:
            if not isinstance(current, dict):
                return ()
            current = current.get(part)
            if current is None:
                return ()
        return tuple(self._collect_url_candidates(current))

    def _collect_url_candidates(self, payload: object) -> Iterable[str]:
        if isinstance(payload, str):
            if payload.startswith(("http://", "https://")):
                yield payload
            elif payload.startswith("//"):
                yield f"https:{payload}"
            return
        if isinstance(payload, list):
            for item in payload:
                yield from self._collect_url_candidates(item)
            return
        if isinstance(payload, dict):
            for key in ("url", "src"):
                value = payload.get(key)
                if isinstance(value, str):
                    yield from self._collect_url_candidates(value)
            for key in ("url_list", "urlList"):
                value = payload.get(key)
                if isinstance(value, list):
                    yield from self._collect_url_candidates(value)
            for key in ("image_url", "imageURL", "imageUrl", "image", "display_image", "displayImage", "display_url", "thumbnails"):
                value = payload.get(key)
                if value is not None:
                    yield from self._collect_url_candidates(value)

    def _choose_preferred_image_url(self, urls: Iterable[str]) -> str | None:
        deduped_urls = self._dedupe_urls(self._normalize_image_url(url) for url in urls)
        if not deduped_urls:
            return None
        return max(deduped_urls, key=self._score_image_url)

    def _score_image_url(self, url: str) -> tuple[int, int]:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path.lower()
        score = 0
        if parsed.scheme == "https":
            score += 40
        elif parsed.scheme == "http":
            score += 10
        if "/obj/" in path:
            score += 25
        if any(marker in host for marker in ("tiktokcdn.com", "byteimg.com", "ibytedtos.com")):
            score += 20
        if self._is_broken_tiktok_image_host(host):
            score -= 80
        if any(path.endswith(f".{extension}") for extension in ("jpg", "jpeg", "png", "webp")):
            score += 5
        return score, -len(url)

    @staticmethod
    def _dedupe_urls(urls: Iterable[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for url in urls:
            sanitized = url.strip()
            if not sanitized or sanitized in seen:
                continue
            seen.add(sanitized)
            deduped.append(sanitized)
        return deduped

    def _dedupe_image_selections(self, selections: Iterable[_TikTokImageSelection]) -> list[_TikTokImageSelection]:
        deduped: list[_TikTokImageSelection] = []
        seen: set[str] = set()
        for selection in selections:
            if selection.url in seen:
                continue
            seen.add(selection.url)
            deduped.append(selection)
        return deduped

    def _score_image_selection_set(self, selections: list[_TikTokImageSelection]) -> tuple[int, int, int]:
        broken_hosts = sum(
            1
            for selection in selections
            if self._is_broken_tiktok_image_host(urlparse(selection.url).hostname or "")
        )
        uses_fallback_fields = any(selection.fallback_fields_considered for selection in selections)
        return (
            len(selections),
            0 if uses_fallback_fields else 1,
            -broken_hosts,
        )

    def _extract_audio_url(self, info: dict[str, object], web_state: dict[str, object]) -> str | None:
        formats = info.get("formats")
        if isinstance(formats, list):
            for item in formats:
                if not isinstance(item, dict):
                    continue
                candidate = str(item.get("url") or "")
                if candidate and ("music" in candidate or item.get("vcodec") == "none" or item.get("format_id") == "audio"):
                    return candidate
        candidates = self._find_audio_urls_in_mapping(web_state)
        return candidates[0] if candidates else None

    @staticmethod
    def _extract_video_url(info: dict[str, object]) -> str | None:
        formats = info.get("formats")
        if not isinstance(formats, list):
            return None
        for item in formats:
            if not isinstance(item, dict):
                continue
            if item.get("vcodec") not in {None, "none"} and str(item.get("url") or "").startswith("http"):
                return str(item["url"])
        return None

    def _extract_thumbnail_url(self, info: dict[str, object], web_state: dict[str, object]) -> str | None:
        thumbnails = info.get("thumbnails")
        thumbnail = self._pick_first_url(thumbnails)
        if thumbnail:
            return thumbnail
        return self._pick_first_url(self._find_values(web_state, {"thumbnail", "cover", "originCover", "origin_cover"}))

    @staticmethod
    def _extract_title(info: dict[str, object], web_state: dict[str, object]) -> str | None:
        return _clean_text(
            str(
                info.get("track")
                or info.get("title")
                or TikTokProvider._pick_first_scalar(web_state, {"title", "desc", "description"})
                or ""
            )
        ) or None

    @staticmethod
    def _extract_author(info: dict[str, object], web_state: dict[str, object]) -> str | None:
        return _clean_text(
            str(
                info.get("uploader")
                or info.get("channel")
                or info.get("creator")
                or TikTokProvider._pick_first_scalar(web_state, {"authorName", "author", "nickname", "unique_id"})
                or ""
            )
        ) or None

    @staticmethod
    def _extract_duration(info: dict[str, object], web_state: dict[str, object]) -> int | None:
        raw_duration = info.get("duration") or TikTokProvider._pick_first_scalar(web_state, {"duration"})
        try:
            return int(raw_duration) if raw_duration is not None else None
        except (TypeError, ValueError):
            return None

    def _find_image_urls_in_mapping(self, payload: object) -> list[str]:
        urls = list(_iter_matching_urls(payload, _IMAGE_URL_PATTERN))
        return [url for url in urls if "avatar" not in url and "cover" not in url]

    def _find_audio_urls_in_mapping(self, payload: object) -> list[str]:
        return list(_iter_matching_urls(payload, _AUDIO_URL_PATTERN))

    @staticmethod
    def _find_values(payload: object, keys: set[str]) -> list[object]:
        found: list[object] = []
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in keys:
                    found.append(value)
                found.extend(TikTokProvider._find_values(value, keys))
        elif isinstance(payload, list):
            for item in payload:
                found.extend(TikTokProvider._find_values(item, keys))
        return found

    @staticmethod
    def _pick_first_scalar(payload: object, keys: set[str]) -> str | None:
        for value in TikTokProvider._find_values(payload, keys):
            if isinstance(value, str) and value.strip():
                return value
        return None

    @staticmethod
    def _pick_first_url(payload: object) -> str | None:
        if isinstance(payload, str) and payload.startswith("http"):
            return payload
        if isinstance(payload, dict):
            for key in ("url", "src", "image", "display_image", "displayImage"):
                candidate = payload.get(key)
                if isinstance(candidate, str) and candidate.startswith("http"):
                    return candidate
            for key in ("url_list", "urlList"):
                candidate = payload.get(key)
                if isinstance(candidate, list):
                    for item in candidate:
                        if isinstance(item, str) and item.startswith("http"):
                            return item
        if isinstance(payload, list):
            for item in payload:
                candidate = TikTokProvider._pick_first_url(item)
                if candidate:
                    return candidate
        return None

    @staticmethod
    def _guess_extension(url: str, *, default: str) -> str:
        path = urlparse(url).path.lower()
        for extension in ("jpg", "jpeg", "png", "webp", "mp3", "m4a", "aac"):
            if path.endswith(f".{extension}"):
                return extension
        return default

    @staticmethod
    def _default_headers() -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        }

    @staticmethod
    def _normalize_image_url(url: str) -> str:
        cleaned = url.strip()
        if cleaned.startswith("//"):
            cleaned = f"https:{cleaned}"
        parsed = urlparse(cleaned)
        host = (parsed.hostname or "").lower()
        if cleaned.startswith("http://") and any(marker in host for marker in ("muscdn.com", "tiktokcdn.com", "byteimg.com")):
            return "https://" + cleaned.removeprefix("http://")
        return cleaned

    @staticmethod
    def _asset_headers(url: str) -> dict[str, str]:
        host = (urlparse(url).hostname or "").lower()
        if any(marker in host for marker in ("muscdn.com", "tiktokcdn.com", "byteimg.com")):
            return dict(_TIKTOK_BROWSER_HEADERS)
        return TikTokProvider._default_headers()

    @staticmethod
    def _is_broken_tiktok_image_host(host: str) -> bool:
        lowered = host.lower()
        return "muscdn.com" in lowered


def _clean_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _iter_matching_urls(payload: object, pattern: re.Pattern[str]) -> Iterable[str]:
    if isinstance(payload, str):
        for match in pattern.findall(payload):
            yield match
        return
    if isinstance(payload, dict):
        for value in payload.values():
            yield from _iter_matching_urls(value, pattern)
        return
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_matching_urls(item, pattern)
