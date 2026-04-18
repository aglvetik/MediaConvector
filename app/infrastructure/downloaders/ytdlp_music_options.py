from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.domain.errors import MusicDownloadError
from app.infrastructure.logging import log_event


def build_music_ytdlp_options(
    base_options: dict[str, Any],
    *,
    cookies_file: Path | None,
    logger: logging.Logger,
    operation: str,
) -> dict[str, Any]:
    options = dict(base_options)
    if cookies_file is None:
        return options

    resolved_path = cookies_file.expanduser()
    if not resolved_path.is_absolute():
        resolved_path = Path.cwd() / resolved_path
    resolved_path = resolved_path.resolve()

    if not resolved_path.exists() or not resolved_path.is_file():
        log_event(
            logger,
            logging.ERROR,
            "music_ytdlp_cookies_missing",
            operation=operation,
            cookies_file=str(resolved_path),
        )
        raise MusicDownloadError(
            "Configured yt-dlp cookies file does not exist.",
            context={"operation": operation, "cookies_file": str(resolved_path)},
        )

    # yt-dlp Python API uses `cookiefile`, which is the equivalent of CLI `--cookies <path>`.
    options["cookiefile"] = str(resolved_path)
    return options
