from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from app.domain.entities.media_result import DeliveryReceipt, MediaMetadata
from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.enums.platform import Platform
from app.domain.errors import (
    AudioExtractionError,
    InvalidCachedMediaError,
    MediaTooLargeError,
    NormalizationError,
    TelegramDeliveryError,
)
from app.domain.policies import build_cache_key
from app.infrastructure.providers.tiktok.url_utils import extract_first_tiktok_url, extract_video_id


class FakeProvider:
    platform_name = Platform.TIKTOK.value

    def __init__(self) -> None:
        self.download_calls: dict[str, int] = defaultdict(int)
        self.has_audio: dict[str, bool] = defaultdict(lambda: True)
        self.invalid_urls: set[str] = set()

    def extract_first_url(self, text: str) -> str | None:
        return extract_first_tiktok_url(text)

    def can_handle(self, url: str) -> bool:
        return "tiktok.com" in url

    async def normalize(self, url: str) -> NormalizedResource:
        if url in self.invalid_urls:
            raise NormalizationError("invalid url")
        resource_id = extract_video_id(url)
        if resource_id is None:
            raise NormalizationError("missing video id")
        return NormalizedResource(
            platform=Platform.TIKTOK,
            resource_type="video",
            resource_id=resource_id,
            normalized_key=build_cache_key(Platform.TIKTOK, "video", resource_id),
            original_url=url,
            canonical_url=url.split("?", 1)[0],
        )

    async def fetch_metadata(self, normalized: NormalizedResource) -> MediaMetadata:
        return MediaMetadata(
            title="video",
            duration_sec=10,
            author="author",
            description="desc",
            size_bytes=1024,
            has_audio=self.has_audio[normalized.normalized_key],
        )

    async def download_video(self, normalized: NormalizedResource, work_dir: Path) -> Path:
        self.download_calls[normalized.normalized_key] += 1
        path = work_dir / f"{normalized.resource_id}.mp4"
        path.write_bytes(b"video-bytes")
        return path


class FakeFfmpegAdapter:
    def __init__(self) -> None:
        self.fail_keys: set[str] = set()
        self.no_audio_keys: set[str] = set()
        self.calls: dict[str, int] = defaultdict(int)

    async def extract_audio(self, video_path: Path, output_path: Path, *, normalized_key: str) -> Path:
        self.calls[normalized_key] += 1
        if normalized_key in self.no_audio_keys:
            raise AudioExtractionError("no audio", no_audio_track=True)
        if normalized_key in self.fail_keys:
            raise AudioExtractionError("ffmpeg failed")
        output_path.write_bytes(b"audio-bytes")
        return output_path


@dataclass(slots=True)
class FakeTextMessage:
    chat_id: int
    text: str
    reply_to_message_id: int | None


class FakeGateway:
    def __init__(self, *, max_file_size_bytes: int = 50 * 1024 * 1024) -> None:
        self.max_file_size_bytes = max_file_size_bytes
        self.next_message_id = 1000
        self.loading_messages: list[tuple[int, int, str]] = []
        self.deleted_messages: list[tuple[int, int]] = []
        self.text_messages: list[FakeTextMessage] = []
        self.sent_video_receipts: list[DeliveryReceipt] = []
        self.sent_audio_receipts: list[DeliveryReceipt] = []
        self.invalid_file_ids: set[str] = set()
        self.fail_audio_upload = False

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
    ) -> DeliveryReceipt:
        if file_id in self.invalid_file_ids:
            raise InvalidCachedMediaError("invalid audio id", media_kind="audio")
        receipt = DeliveryReceipt(file_id=file_id, file_unique_id=f"unique-{file_id}", size_bytes=512)
        self.sent_audio_receipts.append(receipt)
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
        return receipt
