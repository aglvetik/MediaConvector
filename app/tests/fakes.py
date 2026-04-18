from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from app.domain.entities.music_download_artifact import MusicDownloadArtifact
from app.domain.entities.music_search_query import MusicSearchQuery
from app.domain.entities.media_result import DeliveryReceipt, MediaMetadata
from app.domain.entities.music_track import MusicTrack
from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.enums import MusicFailureCode
from app.domain.enums.platform import Platform
from app.domain.errors import (
    AudioExtractionError,
    InvalidCachedMediaError,
    MediaTooLargeError,
    MusicDownloadError,
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


class FakeMusicProvider:
    provider_name = "ytmusic"

    def __init__(self) -> None:
        self.search_calls: dict[str, int] = defaultdict(int)
        self.search_modes: list[tuple[str, bool]] = []
        self.results: dict[str, list[MusicTrack] | None] = {}
        self.fail_queries: set[str] = set()
        self.cookies_fail_queries: set[str] = set()
        self.no_cookie_fail_queries: set[str] = set()

    async def resolve_candidates(
        self,
        query: str,
        *,
        max_candidates: int,
        cookies_file: Path | None = None,
    ) -> list[MusicTrack]:
        self.search_calls[query] += 1
        self.search_modes.append((query, cookies_file is not None))
        if query in self.fail_queries:
            raise MusicDownloadError("search failed")
        if cookies_file is not None and query in self.cookies_fail_queries:
            raise MusicDownloadError(
                "login required",
                error_code=MusicFailureCode.LOGIN_REQUIRED.value,
            )
        if cookies_file is None and query in self.no_cookie_fail_queries:
            raise MusicDownloadError(
                "search failed without cookies",
                error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
            )
        if query in self.results:
            predefined = self.results[query]
            if predefined is None:
                return []
            return predefined[:max_candidates]
        source_id = query.casefold().replace(" ", "_")
        title = " ".join(word.capitalize() for word in query.split())
        return [
            MusicTrack(
                source_id=source_id,
                source_url=f"https://www.youtube.com/watch?v={source_id}",
                canonical_url=f"https://music.youtube.com/watch?v={source_id}",
                title=title,
                performer="Test Artist",
                duration_sec=180,
                thumbnail_url=f"https://img.example/{source_id}.jpg",
                resolver_name="fake_provider",
                source_name="youtube",
                ranking=1,
            )
        ]


class FakeAudioDownloadClient:
    def __init__(self, *, audio_only: bool = True) -> None:
        self.audio_only = audio_only
        self.download_calls: dict[str, int] = defaultdict(int)
        self.download_attempts: list[tuple[str, bool]] = []
        self.thumbnail_calls: dict[str, int] = defaultdict(int)
        self.fail_download_ids: set[str] = set()
        self.cookies_fail_download_ids: set[str] = set()
        self.no_cookie_fail_download_ids: set[str] = set()
        self.fail_thumbnail_ids: set[str] = set()

    async def download_audio_source(
        self,
        track: MusicTrack,
        work_dir: Path,
        *,
        cookies_file: Path | None = None,
    ) -> Path:
        self.download_calls[track.source_id] += 1
        self.download_attempts.append((track.source_id, cookies_file is not None))
        if track.source_id in self.fail_download_ids:
            raise MusicDownloadError("audio download failed")
        if cookies_file is not None and track.source_id in self.cookies_fail_download_ids:
            raise MusicDownloadError(
                "login required",
                error_code=MusicFailureCode.LOGIN_REQUIRED.value,
            )
        if cookies_file is None and track.source_id in self.no_cookie_fail_download_ids:
            raise MusicDownloadError(
                "audio download failed without cookies",
                error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
            )
        path = work_dir / f"{track.source_id}.m4a"
        path.write_bytes(b"music-source-bytes")
        return path

    async def download_track_audio(
        self,
        query: MusicSearchQuery,
        candidate: MusicTrack,
        work_dir: Path,
        *,
        cookies_file: Path | None = None,
    ) -> MusicDownloadArtifact:
        del query
        source_path = await self.download_audio_source(
            candidate,
            work_dir,
            cookies_file=cookies_file,
        )
        return MusicDownloadArtifact(
            source_audio_path=source_path,
            provider_name="youtube_direct",
            canonical_url=candidate.canonical_url,
            source_id=candidate.source_id,
            source_name=candidate.source_name,
        )

    async def download_thumbnail(self, thumbnail_url: str, work_dir: Path, *, fallback_stem: str) -> Path | None:
        self.thumbnail_calls[fallback_stem] += 1
        if fallback_stem in self.fail_thumbnail_ids:
            return None
        path = work_dir / f"{fallback_stem}-thumb.jpg"
        path.write_bytes(b"thumbnail-bytes")
        return path


class FakeRemoteMusicDownloadProvider:
    provider_name = "remote_http"

    def __init__(self) -> None:
        self.configured = True
        self.download_calls: dict[str, int] = defaultdict(int)
        self.download_attempts: list[str] = []
        self.fail_download_ids: set[str] = set()

    async def skip_reason(self) -> str | None:
        if self.configured:
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
        del query
        del cookies_file
        self.download_calls[candidate.source_id] += 1
        self.download_attempts.append(candidate.source_id)
        if candidate.source_id in self.fail_download_ids:
            raise MusicDownloadError(
                "remote download failed",
                error_code=MusicFailureCode.SOURCE_UNAVAILABLE.value,
            )
        path = work_dir / f"remote-{candidate.source_id}.mp3"
        path.write_bytes(b"remote-music-source-bytes")
        return MusicDownloadArtifact(
            source_audio_path=path,
            provider_name=self.provider_name,
            canonical_url=f"https://audio.example/{candidate.source_id}",
            source_id=candidate.source_id,
            source_name=self.provider_name,
        )


class FakeFfmpegAdapter:
    def __init__(self) -> None:
        self.fail_keys: set[str] = set()
        self.no_audio_keys: set[str] = set()
        self.transcode_fail_keys: set[str] = set()
        self.thumbnail_fail_keys: set[str] = set()
        self.calls: dict[str, int] = defaultdict(int)
        self.transcode_calls: dict[str, int] = defaultdict(int)
        self.thumbnail_calls: dict[str, int] = defaultdict(int)

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
    ) -> Path:
        self.transcode_calls[normalized_key] += 1
        if normalized_key in self.transcode_fail_keys:
            raise AudioExtractionError("transcode failed")
        output_path.write_bytes(b"music-mp3-bytes")
        return output_path

    async def prepare_thumbnail(self, source_path: Path, output_path: Path, *, normalized_key: str) -> Path:
        self.thumbnail_calls[normalized_key] += 1
        if normalized_key in self.thumbnail_fail_keys:
            raise AudioExtractionError("thumbnail failed")
        output_path.write_bytes(b"prepared-thumbnail-bytes")
        return output_path


@dataclass(slots=True)
class FakeTextMessage:
    chat_id: int
    text: str
    reply_to_message_id: int | None


@dataclass(slots=True)
class FakeAudioSend:
    chat_id: int
    file_id: str
    title: str | None
    performer: str | None
    caption: str | None
    reply_to_message_id: int | None
    file_name: str | None
    has_thumbnail: bool


class FakeGateway:
    def __init__(self, *, max_file_size_bytes: int = 50 * 1024 * 1024) -> None:
        self.max_file_size_bytes = max_file_size_bytes
        self.next_message_id = 1000
        self.loading_messages: list[tuple[int, int, str]] = []
        self.deleted_messages: list[tuple[int, int]] = []
        self.text_messages: list[FakeTextMessage] = []
        self.sent_video_receipts: list[DeliveryReceipt] = []
        self.sent_audio_receipts: list[DeliveryReceipt] = []
        self.audio_sends: list[FakeAudioSend] = []
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
        *,
        title: str | None = None,
        performer: str | None = None,
        thumbnail_path: Path | None = None,
        file_name: str | None = None,
    ) -> DeliveryReceipt:
        if file_id in self.invalid_file_ids:
            raise InvalidCachedMediaError("invalid audio id", media_kind="audio")
        receipt = DeliveryReceipt(file_id=file_id, file_unique_id=f"unique-{file_id}", size_bytes=512)
        self.sent_audio_receipts.append(receipt)
        self.audio_sends.append(
            FakeAudioSend(
                chat_id=chat_id,
                file_id=file_id,
                title=title,
                performer=performer,
                caption=caption,
                reply_to_message_id=reply_to_message_id,
                file_name=file_name,
                has_thumbnail=thumbnail_path is not None,
            )
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
        thumbnail_path: Path | None = None,
        file_name: str | None = None,
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
        self.audio_sends.append(
            FakeAudioSend(
                chat_id=chat_id,
                file_id=receipt.file_id,
                title=title,
                performer=performer,
                caption=caption,
                reply_to_message_id=reply_to_message_id,
                file_name=file_name,
                has_thumbnail=thumbnail_path is not None,
            )
        )
        return receipt
