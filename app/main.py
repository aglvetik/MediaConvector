from __future__ import annotations

import asyncio
import logging

from aiogram import Dispatcher
from aiogram.types import BotCommand

from app.bootstrap import build_container
from app.config import load_settings
from app.infrastructure.logging import configure_logging, get_logger, log_event
from app.presentation.telegram import build_command_router, build_message_router
from app.presentation.telegram.middlewares import AccessLoggingMiddleware


async def run() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)
    container = build_container(settings)

    await container.cleanup_worker.run_once()
    health_report = await container.health_service.collect()
    log_event(
        logger,
        logging.INFO,
        "startup_diagnostics",
        database_ok=health_report.database_ok,
        temp_dir_ok=health_report.temp_dir_ok,
        ffmpeg_ok=health_report.ffmpeg_ok,
        ytdlp_ok=health_report.ytdlp_ok,
        bot_ready=health_report.bot_ready,
    )

    if settings.bot_mode != "polling":
        raise RuntimeError("Only polling mode is implemented in this version.")

    dispatcher = Dispatcher()
    dispatcher.message.middleware(AccessLoggingMiddleware())
    dispatcher.include_router(build_command_router())
    dispatcher.include_router(build_message_router(process_message_service=container.process_message_service))

    commands = [
        BotCommand(command="start", description="О боте"),
        BotCommand(command="help", description="Помощь"),
    ]
    await container.bot.set_my_commands(commands)
    await container.cleanup_worker.start()
    await container.health_worker.start()
    try:
        await dispatcher.start_polling(container.bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await container.health_worker.stop()
        await container.cleanup_worker.stop()
        await container.bot.session.close()
        await container.database.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
