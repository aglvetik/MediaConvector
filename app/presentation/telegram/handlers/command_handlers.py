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
        "• искать треки по словам «найти», «трек» или «песня»\n\n"
        "Работаю и в личке, и в группах."
    )


def _help_text() -> str:
    return (
        "Как пользоваться:\n\n"
        "1. TikTok\n"
        "Отправь ссылку на TikTok. Я поддерживаю:\n"
        "• видео-посты — пришлю видео и отдельно звук\n"
        "• фото-посты — пришлю фото и отдельно звук\n"
        "• ссылки на звук — пришлю только аудио\n\n"
        "2. Поиск треков\n"
        "Начни сообщение с одного из слов:\n"
        "• найти\n"
        "• трек\n"
        "• песня\n\n"
        "Примеры:\n"
        "• найти Hot Dog Limp Bizkit\n"
        "• трек Linkin Park Numb\n"
        "• песня Metallica One\n\n"
        "Повторные TikTok-ссылки и запросы треков я стараюсь обслуживать быстрее за счет кеша."
    )
