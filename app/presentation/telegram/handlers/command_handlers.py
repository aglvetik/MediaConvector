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
        "Я скачиваю публичные медиа по ссылкам из:\n"
        "• TikTok\n"
        "• YouTube\n"
        "• Instagram\n"
        "• Facebook\n"
        "• Pinterest\n"
        "• Rutube\n"
        "• Likee\n\n"
        "Работаю и в личке, и в группах."
    )


def _help_text() -> str:
    return (
        "Как пользоваться:\n\n"
        "Просто отправь ссылку на публичный пост или медиа.\n\n"
        "Я поддерживаю:\n"
        "• видео — пришлю видео и, если получится, отдельно звук\n"
        "• фото и галереи — пришлю фото\n"
        "• аудио-ссылки — пришлю аудио\n\n"
        "Поддерживаемые платформы:\n"
        "• TikTok\n"
        "• YouTube\n"
        "• Instagram\n"
        "• Facebook\n"
        "• Pinterest\n"
        "• Rutube\n"
        "• Likee\n\n"
        "Работаю только по ссылкам. Поиск музыки по словам не поддерживается."
    )
