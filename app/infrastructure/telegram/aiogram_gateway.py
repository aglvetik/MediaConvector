from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiogram.types import FSInputFile, InputMediaPhoto, Message, ReplyParameters

from app import messages
from app.domain.entities.media_result import DeliveryReceipt
from app.domain.errors import BotForbiddenError, InvalidCachedMediaError, MediaTooLargeError, TelegramDeliveryError
from app.infrastructure.logging import get_logger, log_event


class AiogramTelegramGateway:
    def __init__(self, *, bot: Bot, max_file_size_bytes: int) -> None:
        self._bot = bot
        self._max_file_size_bytes = max_file_size_bytes
        self._logger = get_logger(__name__)

    @property
    def is_ready(self) -> bool:
        return self._bot is not None

    async def send_loading_message(
        self,
        chat_id: int,
        reply_to_message_id: int | None = None,
        *,
        text: str,
    ) -> int:
        message = await self._call_with_retry(
            lambda: self._bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_parameters=self._reply_parameters(reply_to_message_id),
            )
        )
        return message.message_id

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        await self._call_with_retry(lambda: self._bot.delete_message(chat_id=chat_id, message_id=message_id))

    async def send_text(self, chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
        await self._call_with_retry(
            lambda: self._bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_parameters=self._reply_parameters(reply_to_message_id),
            )
        )

    async def send_video_by_file_id(self, chat_id: int, file_id: str, caption: str, reply_to_message_id: int | None = None) -> DeliveryReceipt:
        message = await self._call_with_retry(
            lambda: self._bot.send_video(
                chat_id=chat_id,
                video=file_id,
                caption=caption,
                reply_parameters=self._reply_parameters(reply_to_message_id),
            ),
            media_kind="video",
            cached=True,
        )
        return self._video_receipt_from_message(message)

    async def send_audio_by_file_id(
        self,
        chat_id: int,
        file_id: str,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
        *,
        title: str | None = None,
        performer: str | None = None,
    ) -> DeliveryReceipt:
        message = await self._call_with_retry(
            lambda: self._bot.send_audio(
                chat_id=chat_id,
                audio=file_id,
                caption=caption,
                title=title,
                performer=performer,
                reply_parameters=self._reply_parameters(reply_to_message_id),
            ),
            media_kind="audio",
            cached=True,
        )
        return self._audio_receipt_from_message(message)

    async def send_video_by_upload(self, chat_id: int, file_path: Path, caption: str, reply_to_message_id: int | None = None) -> DeliveryReceipt:
        self._ensure_file_size(file_path)
        message = await self._call_with_retry(
            lambda: self._bot.send_video(
                chat_id=chat_id,
                video=FSInputFile(file_path),
                caption=caption,
                reply_parameters=self._reply_parameters(reply_to_message_id),
            ),
            media_kind="video",
            cached=False,
        )
        return self._video_receipt_from_message(message, file_path)

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
    ) -> DeliveryReceipt:
        self._ensure_file_size(file_path)
        message = await self._call_with_retry(
            lambda: self._bot.send_audio(
                chat_id=chat_id,
                audio=FSInputFile(file_path),
                caption=caption,
                title=title,
                performer=performer,
                thumbnail=FSInputFile(thumbnail_path) if thumbnail_path is not None else None,
                reply_parameters=self._reply_parameters(reply_to_message_id),
            ),
            media_kind="audio",
            cached=False,
        )
        return self._audio_receipt_from_message(message, file_path)

    async def send_photo_by_upload(
        self,
        chat_id: int,
        file_path: Path,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> DeliveryReceipt:
        self._ensure_file_size(file_path)
        message = await self._call_with_retry(
            lambda: self._bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(file_path),
                caption=caption,
                reply_parameters=self._reply_parameters(reply_to_message_id),
            ),
            media_kind="photo",
            cached=False,
        )
        return self._photo_receipt_from_message(message, file_path)

    async def send_photo_by_file_id(
        self,
        chat_id: int,
        file_id: str,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> DeliveryReceipt:
        message = await self._call_with_retry(
            lambda: self._bot.send_photo(
                chat_id=chat_id,
                photo=file_id,
                caption=caption,
                reply_parameters=self._reply_parameters(reply_to_message_id),
            ),
            media_kind="photo",
            cached=True,
        )
        return self._photo_receipt_from_message(message)

    async def send_photo_group_by_upload(
        self,
        chat_id: int,
        file_paths: tuple[Path, ...],
        reply_to_message_id: int | None = None,
    ) -> tuple[DeliveryReceipt, ...]:
        for file_path in file_paths:
            self._ensure_file_size(file_path)
        messages = await self._call_with_retry(
            lambda: self._bot.send_media_group(
                chat_id=chat_id,
                media=[
                    InputMediaPhoto(media=FSInputFile(file_path))
                    for file_path in file_paths
                ],
                reply_parameters=self._reply_parameters(reply_to_message_id),
            ),
            media_kind="photo",
            cached=False,
        )
        return tuple(
            self._photo_receipt_from_message(message, file_path)
            for message, file_path in zip(messages, file_paths, strict=True)
        )

    async def send_photo_group_by_file_id(
        self,
        chat_id: int,
        file_ids: tuple[str, ...],
        reply_to_message_id: int | None = None,
    ) -> tuple[DeliveryReceipt, ...]:
        messages = await self._call_with_retry(
            lambda: self._bot.send_media_group(
                chat_id=chat_id,
                media=[InputMediaPhoto(media=file_id) for file_id in file_ids],
                reply_parameters=self._reply_parameters(reply_to_message_id),
            ),
            media_kind="photo",
            cached=True,
        )
        return tuple(self._photo_receipt_from_message(message) for message in messages)

    async def _call_with_retry(
        self,
        operation: Callable[[], Awaitable[Any]],
        *,
        media_kind: str | None = None,
        cached: bool = False,
    ) -> Any:
        try:
            return await operation()
        except TelegramRetryAfter as exc:
            log_event(self._logger, 30, "telegram_retry_after", retry_after=exc.retry_after, media_kind=media_kind, cached=cached)
            await asyncio.sleep(exc.retry_after)
            return await operation()
        except TelegramForbiddenError as exc:
            raise BotForbiddenError() from exc
        except TelegramBadRequest as exc:
            message = str(exc).lower()
            if cached and any(
                marker in message
                for marker in (
                    "wrong file identifier",
                    "wrong remote file id",
                    "wrong file id",
                    "file_id is invalid",
                    "file reference has expired",
                )
            ):
                raise InvalidCachedMediaError(str(exc), media_kind=media_kind or "unknown") from exc
            if "too big" in message or "file is too big" in message:
                raise MediaTooLargeError() from exc
            raise TelegramDeliveryError(str(exc)) from exc
        except TelegramNetworkError as exc:
            raise TelegramDeliveryError("Telegram network error.", user_message=messages.TEMPORARY_DOWNLOAD_ERROR) from exc

    def _ensure_file_size(self, file_path: Path) -> None:
        if file_path.stat().st_size > self._max_file_size_bytes:
            raise MediaTooLargeError()

    @staticmethod
    def _reply_parameters(reply_to_message_id: int | None) -> ReplyParameters | None:
        if reply_to_message_id is None:
            return None
        return ReplyParameters(message_id=reply_to_message_id)

    @staticmethod
    def _video_receipt_from_message(message: Message, file_path: Path | None = None) -> DeliveryReceipt:
        if message.video is None:
            raise TelegramDeliveryError("Telegram response did not include a video object.")
        return DeliveryReceipt(
            file_id=message.video.file_id,
            file_unique_id=message.video.file_unique_id,
            size_bytes=file_path.stat().st_size if file_path else message.video.file_size,
        )

    @staticmethod
    def _audio_receipt_from_message(message: Message, file_path: Path | None = None) -> DeliveryReceipt:
        if message.audio is None:
            raise TelegramDeliveryError("Telegram response did not include an audio object.")
        return DeliveryReceipt(
            file_id=message.audio.file_id,
            file_unique_id=message.audio.file_unique_id,
            size_bytes=file_path.stat().st_size if file_path else message.audio.file_size,
        )

    @staticmethod
    def _photo_receipt_from_message(message: Message, file_path: Path | None = None) -> DeliveryReceipt:
        if not message.photo:
            raise TelegramDeliveryError("Telegram response did not include a photo object.")
        photo = message.photo[-1]
        return DeliveryReceipt(
            file_id=photo.file_id,
            file_unique_id=photo.file_unique_id,
            size_bytes=file_path.stat().st_size if file_path else photo.file_size,
        )
