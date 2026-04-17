from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from app.infrastructure.logging import get_logger, log_event


class AccessLoggingMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._logger = get_logger(__name__)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.from_user is not None:
            log_event(
                self._logger,
                20,
                "telegram_update_received",
                chat_id=event.chat.id,
                user_id=event.from_user.id,
                message_id=event.message_id,
            )
        return await handler(event, data)

