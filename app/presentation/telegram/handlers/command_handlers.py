from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

def build_command_router() -> Router:
    router = Router(name="command-router")

    @router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        await message.answer(_help_text())

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await message.answer(_help_text())

    return router


def _help_text() -> str:
    return (
        "Отправьте сообщение со ссылкой на TikTok, и бот автоматически начнёт обработку.\n\n"
        "Команды:\n"
        "/start - краткая справка\n"
        "/help - помощь"
    )
