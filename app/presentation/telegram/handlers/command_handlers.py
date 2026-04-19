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
        "Я помогаю скачивать медиа из публичных ссылок TikTok.\n\n"
        "Пришли ссылку на видео или фото-пост, и я верну подходящий результат.\n\n"
        "Работаю и в личных сообщениях, и в группах."
    )


def _help_text() -> str:
    return (
        "Как пользоваться:\n\n"
        "1. Отправь ссылку на публичное видео или фото-пост TikTok.\n"
        "2. Бот сам вернёт видео, фото или отдельное аудио, если оно доступно.\n\n"
        "Если ссылка недоступна или не поддерживается, я отвечу коротким сообщением."
    )
