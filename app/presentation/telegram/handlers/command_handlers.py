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
        "Привет!\n\n"
        "Я скачиваю медиа из публичных ссылок: TikTok, YouTube, Instagram, Facebook, "
        "Pinterest, Rutube и Likee.\n\n"
        "Просто отправь ссылку. Я сам верну видео, фото или аудио, если это доступно.\n\n"
        "Работаю и в личных сообщениях, и в группах."
    )


def _help_text() -> str:
    return (
        "Как пользоваться:\n\n"
        "1. Отправь ссылку на публичный пост или медиа.\n"
        "2. Бот сам определит, что можно вернуть: видео, фото или аудио.\n\n"
        "Если ссылка недоступна или не поддерживается, я отвечу коротким сообщением."
    )
