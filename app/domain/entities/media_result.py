from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums.cache_status import CacheStatus
from app.domain.enums.delivery_status import DeliveryStatus


@dataclass(slots=True, frozen=True)
class MediaMetadata:
    title: str | None = None
    duration_sec: int | None = None
    author: str | None = None
    description: str | None = None
    size_bytes: int | None = None
    has_audio: bool | None = None


@dataclass(slots=True, frozen=True)
class DeliveryReceipt:
    file_id: str
    file_unique_id: str
    size_bytes: int | None = None


@dataclass(slots=True, frozen=True)
class MediaResult:
    delivery_status: DeliveryStatus
    cache_status: CacheStatus
    video_receipt: DeliveryReceipt | None
    audio_receipt: DeliveryReceipt | None
    has_audio: bool
    cache_hit: bool
    photo_receipts: tuple[DeliveryReceipt, ...] = ()
    user_notice: str | None = None
