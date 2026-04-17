from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app.application.services import IncomingMessage, ProcessMessageService
from app.domain.errors import AppError, ProcessingConflictError


def build_message_router(*, process_message_service: ProcessMessageService) -> Router:
    router = Router(name="message-router")

    @router.message(F.text & ~F.text.startswith("/"))
    async def text_message_handler(message: Message) -> None:
        if message.from_user is None or message.text is None:
            return
        incoming = IncomingMessage(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            message_id=message.message_id,
            chat_type=message.chat.type,
            text=message.text,
        )
        try:
            await process_message_service.handle_message(incoming)
        except ProcessingConflictError:
            return
        except AppError as exc:
            if exc.user_message:
                await message.answer(exc.user_message)

    return router
