from __future__ import annotations

from pathlib import Path

from app import messages
from app.domain.entities.cache_entry import CacheEntry
from app.domain.entities.media_request import MediaRequest
from app.domain.entities.media_result import DeliveryReceipt, MediaResult
from app.domain.errors import AppError, InvalidCachedMediaError
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
            "telegram_delivery_started",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
            cached=True,
            resource_type=cache_entry.resource_type,
        )
        if cache_entry.resource_type == "photo_post":
            result = await self._deliver_photo_post_from_cache(request, cache_entry)
        elif cache_entry.resource_type == "music_only":
            result = await self._deliver_primary_audio_from_cache(
                request,
                audio_file_id=cache_entry.audio_file_id,
                has_audio=cache_entry.has_audio,
                title=request.normalized_resource.title,
                performer=request.normalized_resource.author,
            )
        else:
            result = await self._deliver_video_from_cache(request, cache_entry)
        log_event(
            self._logger,
            20,
            "telegram_delivery_finished",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
            cached=True,
            resource_type=cache_entry.resource_type,
            delivery_status=result.delivery_status.value,
        )
        return result

    async def deliver_uploads(
        self,
        request: MediaRequest,
        video_path: Path,
        audio_path: Path | None,
        *,
        audio_title: str | None = None,
        audio_performer: str | None = None,
        audio_duration_sec: int | None = None,
        audio_thumbnail_path: Path | None = None,
        audio_filename: str | None = None,
        missing_audio_notice: str = messages.NO_AUDIO_TRACK,
    ) -> MediaResult:
        log_event(
            self._logger,
            20,
            "telegram_delivery_started",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
            cached=False,
            resource_type=request.normalized_resource.resource_type,
        )
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

        audio_receipt, notice = await self._send_optional_audio_upload(
            request,
            audio_path,
            missing_audio_notice=missing_audio_notice,
            title=audio_title,
            performer=audio_performer,
            duration_sec=audio_duration_sec,
            thumbnail_path=audio_thumbnail_path,
            filename=audio_filename,
        )
        result = self._build_result(
            primary_sent=True,
            audio_requested=True,
            audio_receipt=audio_receipt,
            cache_hit=False,
            notice=notice,
            video_receipt=video_receipt,
        )
        log_event(
            self._logger,
            20,
            "telegram_delivery_finished",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
            cached=False,
            resource_type=request.normalized_resource.resource_type,
            delivery_status=result.delivery_status.value,
        )
        return result

    async def deliver_photo_post_uploads(
        self,
        request: MediaRequest,
        photo_paths: tuple[Path, ...],
        audio_path: Path | None,
        *,
        audio_expected: bool = True,
        missing_audio_notice: str | None = messages.NO_AUDIO_TRACK,
        audio_title: str | None = None,
        audio_performer: str | None = None,
        audio_duration_sec: int | None = None,
        audio_thumbnail_path: Path | None = None,
        audio_filename: str | None = None,
    ) -> MediaResult:
        log_event(
            self._logger,
            20,
            "gallery_delivery_started",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
            image_count=len(photo_paths),
            cached=False,
        )
        log_event(
            self._logger,
            20,
            "telegram_delivery_started",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
            cached=False,
            resource_type=request.normalized_resource.resource_type,
        )
        photo_receipts = await self._send_photo_group_with_fallback(
            request,
            photo_paths=photo_paths,
            cached=False,
        )
        audio_receipt: DeliveryReceipt | None = None
        notice: str | None = None
        if audio_expected:
            audio_receipt, notice = await self._send_optional_audio_upload(
                request,
                audio_path,
                missing_audio_notice=missing_audio_notice,
                title=audio_title,
                performer=audio_performer,
                duration_sec=audio_duration_sec,
                thumbnail_path=audio_thumbnail_path,
                filename=audio_filename,
            )
        result = self._build_result(
            primary_sent=bool(photo_receipts),
            audio_requested=audio_expected,
            audio_receipt=audio_receipt,
            cache_hit=False,
            notice=notice,
            photo_receipts=photo_receipts,
        )
        log_event(
            self._logger,
            20,
            "telegram_delivery_finished",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
            cached=False,
            resource_type=request.normalized_resource.resource_type,
            delivery_status=result.delivery_status.value,
        )
        log_event(
            self._logger,
            20,
            "gallery_delivery_finished",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
            image_count=len(photo_receipts),
            cached=False,
            delivery_status=result.delivery_status.value,
        )
        return result

    async def deliver_audio_only(
        self,
        request: MediaRequest,
        audio_path: Path | None,
        *,
        missing_audio_notice: str = messages.NO_AUDIO_TRACK,
        primary_delivered: bool = False,
        title: str | None = None,
        performer: str | None = None,
        duration_sec: int | None = None,
        thumbnail_path: Path | None = None,
        filename: str | None = None,
        failure_notice: str = messages.SEPARATE_AUDIO_SEND_FAILED,
        cache_hit: bool = False,
    ) -> MediaResult:
        log_event(
            self._logger,
            20,
            "telegram_delivery_started",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
            cached=cache_hit,
            resource_type=request.normalized_resource.resource_type,
        )
        if audio_path is None:
            await self._gateway.send_text(request.chat_id, missing_audio_notice, request.message_id)
            result = self._build_result(
                primary_sent=primary_delivered,
                audio_requested=True,
                audio_receipt=None,
                cache_hit=cache_hit,
                notice=missing_audio_notice,
            )
            log_event(
                self._logger,
                20,
                "telegram_delivery_finished",
                request_id=request.request_id,
                chat_id=request.chat_id,
                normalized_key=request.normalized_resource.normalized_key,
                source_type=request.normalized_resource.platform.value,
                cached=cache_hit,
                resource_type=request.normalized_resource.resource_type,
                delivery_status=result.delivery_status.value,
            )
            return result

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
                title=title,
                performer=performer,
                duration=duration_sec,
                thumbnail_path=thumbnail_path,
                filename=filename,
            )
            log_event(
                self._logger,
                20,
                "telegram_audio_metadata_sent",
                request_id=request.request_id,
                chat_id=request.chat_id,
                normalized_key=request.normalized_resource.normalized_key,
                title=title,
                performer=performer,
                duration_sec=duration_sec,
                thumbnail_used=thumbnail_path is not None,
                filename=filename,
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
            notice = exc.user_message or failure_notice
            await self._gateway.send_text(request.chat_id, notice, request.message_id)
            result = self._build_result(
                primary_sent=primary_delivered,
                audio_requested=True,
                audio_receipt=None,
                cache_hit=cache_hit,
                notice=notice,
            )
            log_event(
                self._logger,
                20,
                "telegram_delivery_finished",
                request_id=request.request_id,
                chat_id=request.chat_id,
                normalized_key=request.normalized_resource.normalized_key,
                source_type=request.normalized_resource.platform.value,
                cached=cache_hit,
                resource_type=request.normalized_resource.resource_type,
                delivery_status=result.delivery_status.value,
            )
            return result
        except Exception:
            await self._gateway.send_text(request.chat_id, failure_notice, request.message_id)
            result = self._build_result(
                primary_sent=primary_delivered,
                audio_requested=True,
                audio_receipt=None,
                cache_hit=cache_hit,
                notice=failure_notice,
            )
            log_event(
                self._logger,
                20,
                "telegram_delivery_finished",
                request_id=request.request_id,
                chat_id=request.chat_id,
                normalized_key=request.normalized_resource.normalized_key,
                source_type=request.normalized_resource.platform.value,
                cached=cache_hit,
                resource_type=request.normalized_resource.resource_type,
                delivery_status=result.delivery_status.value,
            )
            return result

        result = self._build_result(
            primary_sent=True,
            audio_requested=True,
            audio_receipt=audio_receipt,
            cache_hit=cache_hit,
        )
        log_event(
            self._logger,
            20,
            "telegram_delivery_finished",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
            cached=cache_hit,
            resource_type=request.normalized_resource.resource_type,
            delivery_status=result.delivery_status.value,
        )
        return result

    async def deliver_audio_from_cache(
        self,
        request: MediaRequest,
        audio_file_id: str,
        *,
        title: str | None = None,
        performer: str | None = None,
        duration: int | None = None,
    ) -> MediaResult:
        audio_receipt = await self._gateway.send_audio_by_file_id(
            request.chat_id,
            audio_file_id,
            messages.AUDIO_SUCCESS_CAPTION,
            request.message_id,
            title=title,
            performer=performer,
            duration=duration,
        )
        return self._build_result(
            primary_sent=True,
            audio_requested=True,
            audio_receipt=audio_receipt,
            cache_hit=True,
        )

    async def _deliver_video_from_cache(self, request: MediaRequest, cache_entry: CacheEntry) -> MediaResult:
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

        audio_receipt, notice = await self._send_optional_audio_from_cache(
            request,
            cache_entry,
            primary_sent=True,
        )
        return self._build_result(
            primary_sent=True,
            audio_requested=True,
            audio_receipt=audio_receipt,
            cache_hit=True,
            notice=notice,
            video_receipt=video_receipt,
        )

    async def _deliver_photo_post_from_cache(self, request: MediaRequest, cache_entry: CacheEntry) -> MediaResult:
        log_event(
            self._logger,
            20,
            "gallery_delivery_started",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
            image_count=len(cache_entry.photo_file_ids),
            cached=True,
        )
        photo_receipts = await self._send_photo_group_with_fallback(
            request,
            photo_file_ids=cache_entry.photo_file_ids,
            cached=True,
        )
        if not cache_entry.has_audio:
            result = self._build_result(
                primary_sent=bool(photo_receipts),
                audio_requested=False,
                audio_receipt=None,
                cache_hit=True,
                photo_receipts=photo_receipts,
            )
            log_event(
                self._logger,
                20,
                "gallery_delivery_finished",
                request_id=request.request_id,
                chat_id=request.chat_id,
                normalized_key=request.normalized_resource.normalized_key,
                source_type=request.normalized_resource.platform.value,
                image_count=len(photo_receipts),
                cached=True,
                delivery_status=result.delivery_status.value,
            )
            return result
        audio_receipt, notice = await self._send_optional_audio_from_cache(
            request,
            cache_entry,
            primary_sent=bool(photo_receipts),
        )
        result = self._build_result(
            primary_sent=bool(photo_receipts),
            audio_requested=True,
            audio_receipt=audio_receipt,
            cache_hit=True,
            notice=notice,
            photo_receipts=photo_receipts,
        )
        log_event(
            self._logger,
            20,
            "gallery_delivery_finished",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            source_type=request.normalized_resource.platform.value,
            image_count=len(photo_receipts),
            cached=True,
            delivery_status=result.delivery_status.value,
        )
        return result

    async def _deliver_primary_audio_from_cache(
        self,
        request: MediaRequest,
        *,
        audio_file_id: str | None,
        has_audio: bool,
        title: str | None = None,
        performer: str | None = None,
    ) -> MediaResult:
        if audio_file_id is None:
            if has_audio:
                raise InvalidCachedMediaError(
                    "Cached audio is missing while source audio is expected.",
                    media_kind="audio",
                    context={"reason": "missing_cached_audio"},
                )
            await self._gateway.send_text(request.chat_id, messages.NO_AUDIO_TRACK, request.message_id)
            return self._build_result(
                primary_sent=False,
                audio_requested=True,
                audio_receipt=None,
                cache_hit=True,
                notice=messages.NO_AUDIO_TRACK,
            )

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
            audio_file_id,
            messages.AUDIO_SUCCESS_CAPTION,
            request.message_id,
            title=title,
            performer=performer,
            duration=request.normalized_resource.duration_sec,
        )
        log_event(
            self._logger,
            20,
            "telegram_audio_metadata_sent",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            title=title,
            performer=performer,
            duration_sec=request.normalized_resource.duration_sec,
            thumbnail_used=False,
            filename=None,
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
        return self._build_result(
            primary_sent=True,
            audio_requested=True,
            audio_receipt=audio_receipt,
            cache_hit=True,
        )

    async def _send_optional_audio_from_cache(
        self,
        request: MediaRequest,
        cache_entry: CacheEntry,
        *,
        primary_sent: bool,
    ) -> tuple[DeliveryReceipt | None, str | None]:
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
                    title=request.normalized_resource.title,
                    performer=request.normalized_resource.author,
                    duration=cache_entry.duration_sec or request.normalized_resource.duration_sec,
                )
                log_event(
                    self._logger,
                    20,
                    "telegram_audio_metadata_sent",
                    request_id=request.request_id,
                    chat_id=request.chat_id,
                    normalized_key=request.normalized_resource.normalized_key,
                    title=request.normalized_resource.title,
                    performer=request.normalized_resource.author,
                    duration_sec=cache_entry.duration_sec or request.normalized_resource.duration_sec,
                    thumbnail_used=False,
                    filename=None,
                )
            except InvalidCachedMediaError as exc:
                preserved_context = {
                    key: value for key, value in exc.context.items() if key not in {"video_sent", "media_kind"}
                }
                raise InvalidCachedMediaError(
                    str(exc),
                    media_kind="audio",
                    video_sent=primary_sent,
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
            return audio_receipt, None

        if cache_entry.has_audio:
            raise InvalidCachedMediaError(
                "Cached audio is missing while source audio is expected.",
                media_kind="audio",
                video_sent=primary_sent,
                context={"reason": "missing_cached_audio"},
            )

        await self._gateway.send_text(request.chat_id, messages.NO_AUDIO_TRACK, request.message_id)
        return None, messages.NO_AUDIO_TRACK

    async def _send_optional_audio_upload(
        self,
        request: MediaRequest,
        audio_path: Path | None,
        *,
        missing_audio_notice: str | None,
        title: str | None = None,
        performer: str | None = None,
        duration_sec: int | None = None,
        thumbnail_path: Path | None = None,
        filename: str | None = None,
    ) -> tuple[DeliveryReceipt | None, str | None]:
        if audio_path is None:
            if missing_audio_notice is not None:
                await self._gateway.send_text(request.chat_id, missing_audio_notice, request.message_id)
                log_event(
                    self._logger,
                    20,
                    "partial_delivery",
                    request_id=request.request_id,
                    normalized_key=request.normalized_resource.normalized_key,
                    reason="audio_not_delivered",
                    notice=missing_audio_notice,
                )
            return None, missing_audio_notice

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
                title=title,
                performer=performer,
                duration=duration_sec,
                thumbnail_path=thumbnail_path,
                filename=filename,
            )
            log_event(
                self._logger,
                20,
                "telegram_audio_metadata_sent",
                request_id=request.request_id,
                chat_id=request.chat_id,
                normalized_key=request.normalized_resource.normalized_key,
                title=title,
                performer=performer,
                duration_sec=duration_sec,
                thumbnail_used=thumbnail_path is not None,
                filename=filename,
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
            return audio_receipt, None
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
            return None, notice
        except Exception:
            await self._gateway.send_text(request.chat_id, messages.SEPARATE_AUDIO_SEND_FAILED, request.message_id)
            log_event(
                self._logger,
                30,
                "partial_delivery",
                request_id=request.request_id,
                normalized_key=request.normalized_resource.normalized_key,
                reason="audio_send_failed",
            )
            return None, messages.SEPARATE_AUDIO_SEND_FAILED

    async def _send_photo_group_with_fallback(
        self,
        request: MediaRequest,
        *,
        photo_paths: tuple[Path, ...] = (),
        photo_file_ids: tuple[str, ...] = (),
        cached: bool,
    ) -> tuple[DeliveryReceipt, ...]:
        if not photo_paths and not photo_file_ids:
            return ()
        total_items = len(photo_paths or photo_file_ids)

        log_event(
            self._logger,
            20,
            "telegram_send_photo_group_started",
            request_id=request.request_id,
            chat_id=request.chat_id,
            normalized_key=request.normalized_resource.normalized_key,
            cached=cached,
            photo_count=total_items,
        )
        if total_items == 1:
            if cached:
                receipts = (
                    await self._gateway.send_photo_by_file_id(
                        request.chat_id,
                        photo_file_ids[0],
                        reply_to_message_id=request.message_id,
                    ),
                )
            else:
                receipts = (
                    await self._gateway.send_photo_by_upload(
                        request.chat_id,
                        photo_paths[0],
                        reply_to_message_id=request.message_id,
                    ),
                )
            log_event(
                self._logger,
                20,
                "telegram_send_photo_group_finished",
                request_id=request.request_id,
                chat_id=request.chat_id,
                normalized_key=request.normalized_resource.normalized_key,
                cached=cached,
                fallback=False,
                photo_count=1,
            )
            return receipts
        try:
            if cached:
                receipts = await self._gateway.send_photo_group_by_file_id(
                    request.chat_id,
                    photo_file_ids,
                    request.message_id,
                )
            else:
                receipts = await self._gateway.send_photo_group_by_upload(
                    request.chat_id,
                    photo_paths,
                    request.message_id,
                )
            log_event(
                self._logger,
                20,
                "telegram_send_photo_group_finished",
                request_id=request.request_id,
                chat_id=request.chat_id,
                normalized_key=request.normalized_resource.normalized_key,
                cached=cached,
                fallback=False,
                photo_count=len(receipts),
            )
            return receipts
        except InvalidCachedMediaError:
            raise
        except Exception:
            receipts = await self._send_photos_sequentially(
                request,
                photo_paths=photo_paths,
                photo_file_ids=photo_file_ids,
                cached=cached,
            )
            log_event(
                self._logger,
                20,
                "telegram_send_photo_group_finished",
                request_id=request.request_id,
                chat_id=request.chat_id,
                normalized_key=request.normalized_resource.normalized_key,
                cached=cached,
                fallback=True,
                photo_count=len(receipts),
            )
            return receipts

    async def _send_photos_sequentially(
        self,
        request: MediaRequest,
        *,
        photo_paths: tuple[Path, ...] = (),
        photo_file_ids: tuple[str, ...] = (),
        cached: bool,
    ) -> tuple[DeliveryReceipt, ...]:
        receipts: list[DeliveryReceipt] = []
        if cached:
            for file_id in photo_file_ids:
                receipts.append(
                    await self._gateway.send_photo_by_file_id(
                        request.chat_id,
                        file_id,
                        reply_to_message_id=request.message_id,
                    )
                )
            return tuple(receipts)

        for file_path in photo_paths:
            receipts.append(
                await self._gateway.send_photo_by_upload(
                    request.chat_id,
                    file_path,
                    reply_to_message_id=request.message_id,
                )
            )
        return tuple(receipts)

    @staticmethod
    def _build_result(
        *,
        primary_sent: bool,
        audio_requested: bool,
        audio_receipt: DeliveryReceipt | None,
        cache_hit: bool,
        notice: str | None = None,
        video_receipt: DeliveryReceipt | None = None,
        photo_receipts: tuple[DeliveryReceipt, ...] = (),
    ) -> MediaResult:
        return MediaResult(
            delivery_status=determine_delivery_status(
                video_sent=primary_sent,
                audio_requested=audio_requested,
                audio_sent=audio_receipt is not None,
            ),
            cache_status=determine_cache_status(
                video_sent=primary_sent,
                audio_requested=audio_requested,
                audio_sent=audio_receipt is not None,
            ),
            video_receipt=video_receipt,
            audio_receipt=audio_receipt,
            has_audio=audio_receipt is not None,
            cache_hit=cache_hit,
            photo_receipts=photo_receipts,
            user_notice=notice,
        )
