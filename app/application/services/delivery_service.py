from __future__ import annotations

from pathlib import Path

from app import messages
from app.domain.entities.cache_entry import CacheEntry
from app.domain.entities.media_request import MediaRequest
from app.domain.entities.media_result import DeliveryReceipt, MediaResult
from app.domain.errors import AppError, InvalidCachedMediaError
from app.domain.enums.cache_status import CacheStatus
from app.domain.enums.delivery_status import DeliveryStatus
from app.domain.interfaces.telegram_gateway import TelegramGateway
from app.domain.policies import determine_cache_status, determine_delivery_status
from app.infrastructure.logging import get_logger, log_event


class DeliveryService:
    def __init__(self, gateway: TelegramGateway) -> None:
        self._gateway = gateway
        self._logger = get_logger(__name__)

    async def send_loading(self, chat_id: int, reply_to_message_id: int | None = None) -> int:
        return await self.send_loading_text(chat_id, messages.LOADING_MESSAGE, reply_to_message_id)

    async def send_loading_text(self, chat_id: int, text: str, reply_to_message_id: int | None = None) -> int:
        return await self._gateway.send_loading_message(chat_id, reply_to_message_id, text=text)

    async def delete_loading(self, chat_id: int, message_id: int) -> None:
        await self._gateway.delete_message(chat_id, message_id)

    async def send_text(self, chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
        await self._gateway.send_text(chat_id, text, reply_to_message_id)

    async def deliver_from_cache(self, request: MediaRequest, cache_entry: CacheEntry) -> MediaResult:
        log_event(
            self._logger,
            20,
            "telegram_send_video_started",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            cached=True,
        )
        video_receipt = await self._gateway.send_video_by_file_id(
            request.chat_id,
            cache_entry.video_file_id,
            messages.VIDEO_SUCCESS_CAPTION,
            request.message_id,
        )
        log_event(
            self._logger,
            20,
            "telegram_send_video_finished",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            cached=True,
        )

        audio_receipt: DeliveryReceipt | None = None
        notice: str | None = None
        if cache_entry.audio_file_id and cache_entry.has_audio:
            log_event(
                self._logger,
                20,
                "telegram_send_audio_started",
                request_id=request.request_id,
                chat_id=request.chat_id,
                normalized_key=request.normalized_resource.normalized_key,
                cached=True,
            )
            try:
                audio_receipt = await self._gateway.send_audio_by_file_id(
                    request.chat_id,
                    cache_entry.audio_file_id,
                    messages.AUDIO_SUCCESS_CAPTION,
                    request.message_id,
                )
            except InvalidCachedMediaError as exc:
                preserved_context = {
                    key: value for key, value in exc.context.items() if key not in {"video_sent", "media_kind"}
                }
                raise InvalidCachedMediaError(
                    str(exc),
                    media_kind="audio",
                    video_sent=True,
                    context=preserved_context,
                ) from exc
            log_event(
                self._logger,
                20,
                "telegram_send_audio_finished",
                request_id=request.request_id,
                chat_id=request.chat_id,
                normalized_key=request.normalized_resource.normalized_key,
                cached=True,
            )
        elif cache_entry.has_audio:
            raise InvalidCachedMediaError(
                "Cached audio is missing while source audio is expected.",
                media_kind="audio",
                video_sent=True,
                context={"reason": "missing_cached_audio"},
            )
        else:
            notice = messages.NO_AUDIO_TRACK
            await self._gateway.send_text(request.chat_id, notice, request.message_id)

        return MediaResult(
            delivery_status=determine_delivery_status(
                video_sent=True,
                audio_requested=True,
                audio_sent=audio_receipt is not None,
            ),
            cache_status=determine_cache_status(
                video_sent=True,
                audio_requested=True,
                audio_sent=audio_receipt is not None,
            ),
            video_receipt=video_receipt,
            audio_receipt=audio_receipt,
            has_audio=audio_receipt is not None,
            cache_hit=True,
            user_notice=notice,
        )

    async def deliver_uploads(
        self,
        request: MediaRequest,
        video_path: Path,
        audio_path: Path | None,
        *,
        missing_audio_notice: str = messages.NO_AUDIO_TRACK,
    ) -> MediaResult:
        log_event(
            self._logger,
            20,
            "telegram_send_video_started",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            cached=False,
        )
        video_receipt = await self._gateway.send_video_by_upload(
            request.chat_id,
            video_path,
            messages.VIDEO_SUCCESS_CAPTION,
            request.message_id,
        )
        log_event(
            self._logger,
            20,
            "telegram_send_video_finished",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            cached=False,
        )

        audio_receipt: DeliveryReceipt | None = None
        notice: str | None = None
        if audio_path is not None:
            try:
                log_event(
                    self._logger,
                    20,
                    "telegram_send_audio_started",
                    request_id=request.request_id,
                    chat_id=request.chat_id,
                    normalized_key=request.normalized_resource.normalized_key,
                    cached=False,
                )
                audio_receipt = await self._gateway.send_audio_by_upload(
                    request.chat_id,
                    audio_path,
                    messages.AUDIO_SUCCESS_CAPTION,
                    request.message_id,
                )
                log_event(
                    self._logger,
                    20,
                    "telegram_send_audio_finished",
                    request_id=request.request_id,
                    chat_id=request.chat_id,
                    normalized_key=request.normalized_resource.normalized_key,
                    cached=False,
                )
            except AppError as exc:
                notice = exc.user_message or messages.SEPARATE_AUDIO_SEND_FAILED
                await self._gateway.send_text(request.chat_id, notice, request.message_id)
                log_event(
                    self._logger,
                    30,
                    "partial_delivery",
                    request_id=request.request_id,
                    normalized_key=request.normalized_resource.normalized_key,
                    reason="audio_send_failed",
                    error_code=exc.error_code,
                )
            except Exception:
                notice = messages.SEPARATE_AUDIO_SEND_FAILED
                await self._gateway.send_text(request.chat_id, notice, request.message_id)
                log_event(
                    self._logger,
                    30,
                    "partial_delivery",
                    request_id=request.request_id,
                    normalized_key=request.normalized_resource.normalized_key,
                    reason="audio_send_failed",
                )
        else:
            notice = missing_audio_notice
            await self._gateway.send_text(request.chat_id, notice, request.message_id)
            log_event(
                self._logger,
                20,
                "partial_delivery",
                request_id=request.request_id,
                normalized_key=request.normalized_resource.normalized_key,
                reason="audio_not_delivered",
                notice=notice,
            )

        return MediaResult(
            delivery_status=determine_delivery_status(
                video_sent=True,
                audio_requested=True,
                audio_sent=audio_receipt is not None,
            ),
            cache_status=determine_cache_status(
                video_sent=True,
                audio_requested=True,
                audio_sent=audio_receipt is not None,
            ),
            video_receipt=video_receipt,
            audio_receipt=audio_receipt,
            has_audio=audio_receipt is not None,
            cache_hit=False,
            user_notice=notice,
        )

    async def deliver_audio_only(
        self,
        request: MediaRequest,
        audio_path: Path | None,
        *,
        missing_audio_notice: str = messages.NO_AUDIO_TRACK,
    ) -> MediaResult:
        if audio_path is None:
            await self._gateway.send_text(request.chat_id, missing_audio_notice, request.message_id)
            return MediaResult(
                delivery_status=determine_delivery_status(video_sent=True, audio_requested=True, audio_sent=False),
                cache_status=determine_cache_status(video_sent=True, audio_requested=True, audio_sent=False),
                video_receipt=None,
                audio_receipt=None,
                has_audio=False,
                cache_hit=False,
                user_notice=missing_audio_notice,
            )
        try:
            audio_receipt = await self._gateway.send_audio_by_upload(
                request.chat_id,
                audio_path,
                messages.AUDIO_SUCCESS_CAPTION,
                request.message_id,
            )
        except AppError as exc:
            notice = exc.user_message or messages.SEPARATE_AUDIO_SEND_FAILED
            await self._gateway.send_text(request.chat_id, notice, request.message_id)
            return MediaResult(
                delivery_status=determine_delivery_status(video_sent=True, audio_requested=True, audio_sent=False),
                cache_status=determine_cache_status(video_sent=True, audio_requested=True, audio_sent=False),
                video_receipt=None,
                audio_receipt=None,
                has_audio=False,
                cache_hit=False,
                user_notice=notice,
            )
        except Exception:
            await self._gateway.send_text(request.chat_id, messages.SEPARATE_AUDIO_SEND_FAILED, request.message_id)
            return MediaResult(
                delivery_status=determine_delivery_status(video_sent=True, audio_requested=True, audio_sent=False),
                cache_status=determine_cache_status(video_sent=True, audio_requested=True, audio_sent=False),
                video_receipt=None,
                audio_receipt=None,
                has_audio=False,
                cache_hit=False,
                user_notice=messages.SEPARATE_AUDIO_SEND_FAILED,
            )
        return MediaResult(
            delivery_status=determine_delivery_status(video_sent=True, audio_requested=True, audio_sent=True),
            cache_status=determine_cache_status(video_sent=True, audio_requested=True, audio_sent=True),
            video_receipt=None,
            audio_receipt=audio_receipt,
            has_audio=True,
            cache_hit=False,
            user_notice=None,
        )

    async def deliver_audio_from_cache(self, request: MediaRequest, audio_file_id: str) -> MediaResult:
        audio_receipt = await self._gateway.send_audio_by_file_id(
            request.chat_id,
            audio_file_id,
            messages.AUDIO_SUCCESS_CAPTION,
            request.message_id,
        )
        return MediaResult(
            delivery_status=determine_delivery_status(video_sent=True, audio_requested=True, audio_sent=True),
            cache_status=determine_cache_status(video_sent=True, audio_requested=True, audio_sent=True),
            video_receipt=None,
            audio_receipt=audio_receipt,
            has_audio=True,
            cache_hit=True,
            user_notice=None,
        )

    async def deliver_music_from_cache(self, request: MediaRequest, cache_entry: CacheEntry) -> MediaResult:
        log_event(
            self._logger,
            20,
            "telegram_send_audio_started",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            cached=True,
        )
        audio_receipt = await self._gateway.send_audio_by_file_id(
            request.chat_id,
            cache_entry.audio_file_id,
            None,
            request.message_id,
            title=cache_entry.title,
            performer=cache_entry.performer,
            file_name=cache_entry.file_name,
        )
        log_event(
            self._logger,
            20,
            "telegram_send_audio_finished",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            cached=True,
        )
        return MediaResult(
            delivery_status=DeliveryStatus.SENT_AUDIO,
            cache_status=CacheStatus.READY,
            video_receipt=None,
            audio_receipt=audio_receipt,
            has_audio=True,
            cache_hit=True,
            user_notice=None,
        )

    async def deliver_music_upload(
        self,
        request: MediaRequest,
        audio_path: Path,
        *,
        title: str | None,
        performer: str | None,
        thumbnail_path: Path | None,
        file_name: str | None,
    ) -> MediaResult:
        log_event(
            self._logger,
            20,
            "telegram_send_audio_started",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            cached=False,
        )
        audio_receipt = await self._gateway.send_audio_by_upload(
            request.chat_id,
            audio_path,
            None,
            request.message_id,
            title=title,
            performer=performer,
            thumbnail_path=thumbnail_path,
            file_name=file_name,
        )
        log_event(
            self._logger,
            20,
            "telegram_send_audio_finished",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            cached=False,
        )
        return MediaResult(
            delivery_status=DeliveryStatus.SENT_AUDIO,
            cache_status=CacheStatus.READY,
            video_receipt=None,
            audio_receipt=audio_receipt,
            has_audio=True,
            cache_hit=False,
            user_notice=None,
        )
