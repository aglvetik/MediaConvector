from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app import messages
from app.domain.entities.media_result import DeliveryReceipt, MediaMetadata
from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.entities.visual_media_entry import VisualMediaEntry
from app.domain.enums.platform import Platform
from app.domain.errors import (
    AudioExtractionError,
    DownloadError,
    InvalidCachedMediaError,
    MediaTooLargeError,
    NormalizationError,
    TelegramDeliveryError,
    UnsupportedUrlError,
)
from app.domain.policies import build_cache_key
from app.infrastructure.providers.source_detection import detect_source_type, extract_first_supported_url
from app.infrastructure.providers.tiktok.url_utils import (
    extract_first_tiktok_url,
    extract_photo_id,
    extract_video_id,
)


class FakeProvider:
    platform_name = Platform.TIKTOK.value

    def __init__(self) -> None:
        self.download_calls: dict[str, int] = defaultdict(int)
        self.audio_download_calls: dict[str, int] = defaultdict(int)
        self.image_download_calls: dict[str, int] = defaultdict(int)
        self.has_audio: dict[str, bool] = defaultdict(lambda: True)
        self.photo_counts: dict[str, int] = defaultdict(lambda: 3)
        self.broken_image_entries: dict[str, set[int]] = defaultdict(set)
        self.audio_fail_keys: set[str] = set()
        self.invalid_urls: set[str] = set()
        self.download_first_gallery_keys: set[str] = set()
        self.photo_extensions: dict[str, tuple[str, ...]] = {}

    def extract_first_url(self, text: str) -> str | None:
        return extract_first_tiktok_url(text)

    def can_handle(self, url: str) -> bool:
        return "tiktok.com" in url

    async def normalize(self, url: str) -> NormalizedResource:
        if url in self.invalid_urls:
            raise NormalizationError("invalid url")

        resource_type = "video"
        resource_id = extract_video_id(url)
        image_urls: tuple[str, ...] = ()
        audio_url: str | None = None
        if "/photo/" in url:
            resource_type = "photo_post"
            resource_id = extract_photo_id(url)
            if resource_id is None:
                raise NormalizationError("missing photo id")
            normalized_key = build_cache_key(Platform.TIKTOK, resource_type, resource_id)
            image_urls = tuple(f"https://example.com/{resource_id}-{index}.jpg" for index in range(1, self.photo_counts[normalized_key] + 1))
            audio_url = f"https://example.com/{resource_id}.m4a"
        elif "/music/" in url:
            raise UnsupportedUrlError(
                "TikTok music links are not supported.",
                user_message=messages.TIKTOK_MUSIC_LINKS_NOT_SUPPORTED,
                error_code="unsupported_resource",
                context={"reason": "tiktok_music_links_not_supported", "url": url},
            )
        elif resource_id is None:
            raise NormalizationError("missing video id")

        normalized_key = build_cache_key(Platform.TIKTOK, resource_type, resource_id)
        photo_extensions = self.photo_extensions.get(normalized_key, ())
        return NormalizedResource(
            platform=Platform.TIKTOK,
            resource_type=resource_type,
            resource_id=resource_id,
            normalized_key=normalized_key,
            original_url=url,
            canonical_url=url.split("?", 1)[0],
            engine_name="gallery-dl" if normalized_key in self.download_first_gallery_keys else "yt-dlp",
            media_kind="gallery" if resource_type == "photo_post" and len(image_urls) > 1 else ("photo" if resource_type == "photo_post" else "video"),
            title=resource_type,
            author="author",
            audio_url=audio_url,
            image_urls=() if normalized_key in self.download_first_gallery_keys else image_urls,
            image_entries=() if normalized_key in self.download_first_gallery_keys else tuple(
                VisualMediaEntry(source_url=image_url, order=index, mime_type_hint="image/jpeg")
                for index, image_url in enumerate(image_urls, start=1)
            ),
            duration_sec=10,
            has_expected_audio=(None if normalized_key in self.download_first_gallery_keys and resource_type == "photo_post" else (audio_url is not None if resource_type != "video" else None)),
        )

    async def fetch_metadata(self, normalized: NormalizedResource) -> MediaMetadata:
        return MediaMetadata(
            title=normalized.title or "media",
            duration_sec=10,
            author=normalized.author or "author",
            description="desc",
            size_bytes=1024,
            has_audio=self.has_audio[normalized.normalized_key],
        )

    async def download_video(self, normalized: NormalizedResource, work_dir: Path) -> Path:
        self.download_calls[normalized.normalized_key] += 1
        path = work_dir / f"{normalized.resource_id}.mp4"
        path.write_bytes(b"video-bytes")
        return path

    async def download_audio(self, normalized: NormalizedResource, work_dir: Path) -> Path | None:
        if normalized.normalized_key in self.audio_fail_keys:
            raise DownloadError("audio download failed", temporary=True)
        if not self.has_audio[normalized.normalized_key]:
            return None
        self.audio_download_calls[normalized.normalized_key] += 1
        path = work_dir / f"{normalized.resource_id}.m4a"
        path.write_bytes(b"audio-bytes")
        return path

    async def download_image_entry(
        self,
        normalized: NormalizedResource,
        work_dir: Path,
        *,
        source_url: str,
        entry_index: int,
    ) -> Path:
        if entry_index == 1:
            self.image_download_calls[normalized.normalized_key] += 1
        if entry_index in self.broken_image_entries[normalized.normalized_key]:
            raise DownloadError("image download failed", temporary=True)
        extension = self._photo_extension(normalized.normalized_key, entry_index)
        path = work_dir / f"{normalized.resource_id}-{entry_index}.{extension}"
        path.write_bytes(f"image-{entry_index}".encode("utf-8"))
        return path

    async def download_images(self, normalized: NormalizedResource, work_dir: Path) -> tuple[Path, ...]:
        paths: list[Path] = []
        total = len(normalized.image_urls) if normalized.image_urls else self.photo_counts[normalized.normalized_key]
        for index in range(1, total + 1):
            path = await self.download_image_entry(
                normalized,
                work_dir,
                source_url=normalized.image_urls[index - 1] if normalized.image_urls else f"https://example.com/{normalized.resource_id}-{index}.jpg",
                entry_index=index,
            )
            paths.append(path)
        return tuple(paths)

    def _photo_extension(self, normalized_key: str, entry_index: int) -> str:
        configured = self.photo_extensions.get(normalized_key, ())
        if configured and entry_index <= len(configured):
            return configured[entry_index - 1]
        return "jpg"


class FakeGenericProvider:
    def __init__(self, platform: Platform) -> None:
        self.platform_name = platform.value
        self._platform = platform
        self.download_calls: dict[str, int] = defaultdict(int)
        self.audio_download_calls: dict[str, int] = defaultdict(int)
        self.image_download_calls: dict[str, int] = defaultdict(int)
        self.broken_image_entries: dict[str, set[int]] = defaultdict(set)
        self.audio_fail_keys: set[str] = set()
        self.download_first_gallery_keys: set[str] = set()
        self.photo_counts: dict[str, int] = defaultdict(lambda: 3)
        self.photo_extensions: dict[str, tuple[str, ...]] = {}

    def extract_first_url(self, text: str) -> str | None:
        return extract_first_supported_url(text, self._platform)

    def can_handle(self, url: str) -> bool:
        return detect_source_type(url) == self._platform

    async def normalize(self, url: str) -> NormalizedResource:
        path = urlparse(url).path.strip("/")
        resource_id = path.rsplit("/", 1)[-1] or "resource"
        lowered = path.casefold()

        if "gallery" in lowered or "photos" in lowered or "carousel" in lowered or "pin" in lowered:
            resource_type = "photo_post"
            photo_count = 1 if "single" in lowered else 3
            image_urls = tuple(f"https://cdn.example/{resource_id}-{index}.jpg" for index in range(1, photo_count + 1))
            audio_url = f"https://cdn.example/{resource_id}.m4a" if "with-audio" in lowered else None
        elif "audio" in lowered or "sound" in lowered:
            resource_type = "music_only"
            image_urls = ()
            audio_url = f"https://cdn.example/{resource_id}.mp3"
        else:
            resource_type = "video"
            image_urls = ()
            audio_url = None

        normalized_key = build_cache_key(self._platform, resource_type, resource_id)
        photo_extensions = self.photo_extensions.get(normalized_key, ())
        return NormalizedResource(
            platform=self._platform,
            resource_type=resource_type,
            resource_id=resource_id,
            normalized_key=normalized_key,
            original_url=url,
            canonical_url=url.split("?", 1)[0],
            engine_name="gallery-dl" if normalized_key in self.download_first_gallery_keys else "yt-dlp",
            media_kind="gallery" if resource_type == "photo_post" and len(image_urls) > 1 else ("photo" if resource_type == "photo_post" else ("audio" if resource_type == "music_only" else "video")),
            title=f"{self._platform.value}-{resource_type}",
            author=f"{self._platform.value}-author",
            audio_url=audio_url,
            image_urls=() if normalized_key in self.download_first_gallery_keys else image_urls,
            image_entries=() if normalized_key in self.download_first_gallery_keys else tuple(
                VisualMediaEntry(source_url=image_url, order=index, mime_type_hint="image/jpeg")
                for index, image_url in enumerate(image_urls, start=1)
            ),
            duration_sec=60,
            has_expected_audio=(None if normalized_key in self.download_first_gallery_keys and resource_type == "photo_post" else (audio_url is not None if resource_type != "video" else None)),
        )

    async def fetch_metadata(self, normalized: NormalizedResource) -> MediaMetadata:
        return MediaMetadata(
            title=normalized.title or "media",
            duration_sec=60,
            author=normalized.author or "author",
            description="desc",
            size_bytes=2048,
            has_audio=normalized.has_expected_audio if normalized.has_expected_audio is not None else True,
        )

    async def download_video(self, normalized: NormalizedResource, work_dir: Path) -> Path:
        self.download_calls[normalized.normalized_key] += 1
        path = work_dir / f"{normalized.resource_id}.mp4"
        path.write_bytes(b"video-bytes")
        return path

    async def download_audio(self, normalized: NormalizedResource, work_dir: Path) -> Path | None:
        self.audio_download_calls[normalized.normalized_key] += 1
        if normalized.normalized_key in self.audio_fail_keys:
            raise DownloadError("audio download failed", temporary=True)
        if normalized.audio_url is None:
            return None
        suffix = ".mp3" if normalized.resource_type == "music_only" else ".m4a"
        path = work_dir / f"{normalized.resource_id}{suffix}"
        path.write_bytes(b"audio-bytes")
        return path

    async def download_image_entry(
        self,
        normalized: NormalizedResource,
        work_dir: Path,
        *,
        source_url: str,
        entry_index: int,
    ) -> Path:
        if entry_index == 1:
            self.image_download_calls[normalized.normalized_key] += 1
        if entry_index in self.broken_image_entries[normalized.normalized_key]:
            raise DownloadError("image download failed", temporary=True)
        extension = self._photo_extension(normalized.normalized_key, entry_index)
        path = work_dir / f"{normalized.resource_id}-{entry_index}.{extension}"
        path.write_bytes(f"image-{entry_index}".encode("utf-8"))
        return path

    async def download_images(self, normalized: NormalizedResource, work_dir: Path) -> tuple[Path, ...]:
        paths: list[Path] = []
        total = len(normalized.image_urls) if normalized.image_urls else self.photo_counts[normalized.normalized_key]
        for index in range(1, total + 1):
            path = await self.download_image_entry(
                normalized,
                work_dir,
                source_url=normalized.image_urls[index - 1] if normalized.image_urls else f"https://cdn.example/{normalized.resource_id}-{index}.jpg",
                entry_index=index,
            )
            paths.append(path)
        return tuple(paths)

    def _photo_extension(self, normalized_key: str, entry_index: int) -> str:
        configured = self.photo_extensions.get(normalized_key, ())
        if configured and entry_index <= len(configured):
            return configured[entry_index - 1]
        return "jpg"


class FakeFfmpegAdapter:
    def __init__(self) -> None:
        self.fail_keys: set[str] = set()
        self.no_audio_keys: set[str] = set()
        self.thumbnail_fail_keys: set[str] = set()
        self.transcode_fail_keys: set[str] = set()
        self.image_normalize_fail_keys: set[str] = set()
        self.calls: dict[str, int] = defaultdict(int)

    async def extract_audio(self, video_path: Path, output_path: Path, *, normalized_key: str) -> Path:
        self.calls[normalized_key] += 1
        if normalized_key in self.no_audio_keys:
            raise AudioExtractionError("no audio", no_audio_track=True)
        if normalized_key in self.fail_keys:
            raise AudioExtractionError("ffmpeg failed")
        output_path.write_bytes(b"audio-bytes")
        return output_path

    async def transcode_audio_to_mp3(
        self,
        source_path: Path,
        output_path: Path,
        *,
        normalized_key: str,
        title: str | None = None,
        performer: str | None = None,
        cover_path: Path | None = None,
    ) -> Path:
        self.calls[f"transcode:{normalized_key}"] += 1
        if normalized_key in self.transcode_fail_keys or normalized_key in self.fail_keys:
            raise AudioExtractionError("transcode failed")
        output_path.write_bytes(b"mp3-bytes")
        return output_path

    async def prepare_audio_thumbnail(self, source_path: Path, output_path: Path, *, normalized_key: str) -> Path:
        self.calls[f"thumbnail:{normalized_key}"] += 1
        if normalized_key in self.thumbnail_fail_keys:
            raise AudioExtractionError("thumbnail failed")
        output_path.write_bytes(b"jpg-bytes")
        return output_path

    async def normalize_image_to_jpg(self, source_path: Path, output_path: Path, *, normalized_key: str) -> Path:
        self.calls[f"image:{normalized_key}"] += 1
        if normalized_key in self.image_normalize_fail_keys:
            raise AudioExtractionError("image normalize failed")
        output_path.write_bytes(b"jpg-bytes")
        return output_path


@dataclass(slots=True)
class FakeTextMessage:
    chat_id: int
    text: str
    reply_to_message_id: int | None


@dataclass(slots=True)
class FakeAudioSend:
    title: str | None
    performer: str | None
    thumbnail_used: bool
    duration: int | None
    filename: str | None


class FakeGateway:
    def __init__(self, *, max_file_size_bytes: int = 50 * 1024 * 1024) -> None:
        self.max_file_size_bytes = max_file_size_bytes
        self.next_message_id = 1000
        self.loading_messages: list[tuple[int, int, str]] = []
        self.deleted_messages: list[tuple[int, int]] = []
        self.text_messages: list[FakeTextMessage] = []
        self.sent_video_receipts: list[DeliveryReceipt] = []
        self.sent_audio_receipts: list[DeliveryReceipt] = []
        self.sent_photo_receipts: list[DeliveryReceipt] = []
        self.sent_audio_requests: list[FakeAudioSend] = []
        self.sent_photo_paths: list[Path] = []
        self.invalid_file_ids: set[str] = set()
        self.fail_audio_upload = False
        self.fail_photo_group_upload = False
        self.fail_photo_group_cached = False

    @property
    def is_ready(self) -> bool:
        return True

    async def send_loading_message(self, chat_id: int, reply_to_message_id: int | None = None, *, text: str) -> int:
        self.next_message_id += 1
        self.loading_messages.append((chat_id, self.next_message_id, text))
        return self.next_message_id

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.deleted_messages.append((chat_id, message_id))

    async def send_text(self, chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
        self.text_messages.append(FakeTextMessage(chat_id, text, reply_to_message_id))

    async def send_video_by_file_id(self, chat_id: int, file_id: str, caption: str, reply_to_message_id: int | None = None) -> DeliveryReceipt:
        if file_id in self.invalid_file_ids:
            raise InvalidCachedMediaError("invalid video id", media_kind="video")
        receipt = DeliveryReceipt(file_id=file_id, file_unique_id=f"unique-{file_id}", size_bytes=1024)
        self.sent_video_receipts.append(receipt)
        return receipt

    async def send_audio_by_file_id(
        self,
        chat_id: int,
        file_id: str,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
        *,
        title: str | None = None,
        performer: str | None = None,
        duration: int | None = None,
    ) -> DeliveryReceipt:
        if file_id in self.invalid_file_ids:
            raise InvalidCachedMediaError("invalid audio id", media_kind="audio")
        receipt = DeliveryReceipt(file_id=file_id, file_unique_id=f"unique-{file_id}", size_bytes=512)
        self.sent_audio_receipts.append(receipt)
        self.sent_audio_requests.append(
            FakeAudioSend(title=title, performer=performer, thumbnail_used=False, duration=duration, filename=None)
        )
        return receipt

    async def send_video_by_upload(self, chat_id: int, file_path: Path, caption: str, reply_to_message_id: int | None = None) -> DeliveryReceipt:
        if file_path.stat().st_size > self.max_file_size_bytes:
            raise MediaTooLargeError()
        receipt = DeliveryReceipt(
            file_id=f"video:{file_path.stem}:{len(self.sent_video_receipts)}",
            file_unique_id=f"video-unique:{file_path.stem}:{len(self.sent_video_receipts)}",
            size_bytes=file_path.stat().st_size,
        )
        self.sent_video_receipts.append(receipt)
        return receipt

    async def send_audio_by_upload(
        self,
        chat_id: int,
        file_path: Path,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
        *,
        title: str | None = None,
        performer: str | None = None,
        duration: int | None = None,
        thumbnail_path: Path | None = None,
        filename: str | None = None,
    ) -> DeliveryReceipt:
        if self.fail_audio_upload:
            raise TelegramDeliveryError("audio upload failed")
        if file_path.stat().st_size > self.max_file_size_bytes:
            raise MediaTooLargeError()
        receipt = DeliveryReceipt(
            file_id=f"audio:{file_path.stem}:{len(self.sent_audio_receipts)}",
            file_unique_id=f"audio-unique:{file_path.stem}:{len(self.sent_audio_receipts)}",
            size_bytes=file_path.stat().st_size,
        )
        self.sent_audio_receipts.append(receipt)
        self.sent_audio_requests.append(
            FakeAudioSend(
                title=title,
                performer=performer,
                thumbnail_used=thumbnail_path is not None,
                duration=duration,
                filename=filename or file_path.name,
            )
        )
        return receipt

    async def send_photo_by_upload(
        self,
        chat_id: int,
        file_path: Path,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> DeliveryReceipt:
        if file_path.stat().st_size > self.max_file_size_bytes:
            raise MediaTooLargeError()
        self.sent_photo_paths.append(file_path)
        receipt = DeliveryReceipt(
            file_id=f"photo:{file_path.stem}:{len(self.sent_photo_receipts)}",
            file_unique_id=f"photo-unique:{file_path.stem}:{len(self.sent_photo_receipts)}",
            size_bytes=file_path.stat().st_size,
        )
        self.sent_photo_receipts.append(receipt)
        return receipt

    async def send_photo_by_file_id(
        self,
        chat_id: int,
        file_id: str,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> DeliveryReceipt:
        if file_id in self.invalid_file_ids:
            raise InvalidCachedMediaError("invalid photo id", media_kind="photo")
        receipt = DeliveryReceipt(file_id=file_id, file_unique_id=f"photo-unique:{file_id}", size_bytes=128)
        self.sent_photo_receipts.append(receipt)
        return receipt

    async def send_photo_group_by_upload(
        self,
        chat_id: int,
        file_paths: tuple[Path, ...],
        reply_to_message_id: int | None = None,
    ) -> tuple[DeliveryReceipt, ...]:
        if self.fail_photo_group_upload:
            raise TelegramDeliveryError("photo group upload failed")
        receipts = [await self.send_photo_by_upload(chat_id, path, reply_to_message_id=reply_to_message_id) for path in file_paths]
        return tuple(receipts)

    async def send_photo_group_by_file_id(
        self,
        chat_id: int,
        file_ids: tuple[str, ...],
        reply_to_message_id: int | None = None,
    ) -> tuple[DeliveryReceipt, ...]:
        if any(file_id in self.invalid_file_ids for file_id in file_ids):
            raise InvalidCachedMediaError("invalid photo id", media_kind="photo")
        if self.fail_photo_group_cached:
            raise TelegramDeliveryError("photo group cached failed")
        receipts = [await self.send_photo_by_file_id(chat_id, file_id, reply_to_message_id=reply_to_message_id) for file_id in file_ids]
        return tuple(receipts)
