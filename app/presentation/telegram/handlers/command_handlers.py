from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message


def build_command_router() -> Router:
    router = Router(name="command-router")

    @router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        await message.answer(_start_text())

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await message.answer(_help_text())

    return router


def _start_text() -> str:
    return (
        "Привет 👋\n\n"
        "Я умею:\n"
        "• скачивать видео из TikTok без водяного знака\n"
        "• отдельно отправлять звук из видео\n"
        "• искать и отправлять треки по запросу\n\n"
        "Работаю и в личке, и в группах."
    )


def _help_text() -> str:
    return (
        "Как пользоваться:\n\n"
        "1. TikTok\n"
        "Просто отправь ссылку на TikTok — я пришлю видео без водяного знака и отдельно звук.\n\n"
        "2. Поиск музыки\n"
        "Начни сообщение с одного из слов:\n"
        "• найти\n"
        "• трек\n"
        "• песня\n\n"
        "Примеры:\n"
        "• найти after dark\n"
        "• трек rammstein sonne\n"
        "• песня in the end slowed\n\n"
        "Если отправляешь один и тот же запрос повторно, я стараюсь использовать кеш, чтобы отвечать быстрее."
    )
