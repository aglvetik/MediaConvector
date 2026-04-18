from __future__ import annotations

import logging
import os
from pathlib import Path

from app.application.services.music_source_health_service import MusicSourceHealthService
from app.domain.entities.music_source_state import MusicSourceState
from app.domain.enums import MusicFailureCode
from app.infrastructure.logging import get_logger, log_event


class StaticCookieFileProvider:
    source_name = "youtube_cookies"

    def __init__(
        self,
        *,
        cookies_file: Path | None,
        health_service: MusicSourceHealthService,
    ) -> None:
        self._cookies_file = cookies_file
        self._health_service = health_service
        self._logger = get_logger(__name__)

    async def get_cookie_file(self) -> Path | None:
        if not self._cookies_file:
            log_event(
                self._logger,
                logging.WARNING,
                "cookies_missing",
                source_name=self.source_name,
                cookies_file=None,
            )
            await self.mark_failure(
                MusicFailureCode.COOKIES_MISSING.value,
                error_message="YTDLP_COOKIES_FILE is not configured.",
            )
            return None

        resolved_path = self._cookies_file.expanduser().resolve(strict=False)

        if not os.path.exists(resolved_path) or not resolved_path.is_file():
            log_event(
                self._logger,
                logging.WARNING,
                "cookies_missing",
                source_name=self.source_name,
                cookies_file=str(resolved_path),
            )
            await self.mark_failure(
                MusicFailureCode.COOKIES_MISSING.value,
                error_message=f"Missing cookies file: {resolved_path}",
            )
            return None

        return resolved_path

    async def mark_success(self) -> None:
        await self._health_service.mark_success(
            self.source_name,
            configured=self._cookies_file is not None,
        )

    async def mark_failure(self, error_code: str, *, error_message: str | None = None) -> None:
        await self._health_service.mark_failure(
            self.source_name,
            configured=self._cookies_file is not None,
            error_code=error_code,
            error_message=error_message,
        )

    async def current_state(self) -> MusicSourceState:
        return await self._health_service.get_state(
            self.source_name,
            configured=self._cookies_file is not None,
        )
