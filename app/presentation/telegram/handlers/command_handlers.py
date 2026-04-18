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
        "• скачивать посты из TikTok\n"
        "• отдельно отправлять звук из TikTok-видео и фото-постов\n"
        "• работать и в личке, и в группах"
    )


def _help_text() -> str:
    return (
        "Как пользоваться:\n\n"
        "Отправь ссылку на TikTok. Я поддерживаю:\n"
        "• видео-посты — пришлю видео и отдельно звук\n"
        "• фото-посты — пришлю фото и отдельно звук\n"
        "• ссылки на звук — пришлю только аудио\n\n"
        "Повторные TikTok-ссылки я стараюсь обслуживать быстрее за счет кеша."
    )
