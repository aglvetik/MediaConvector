from __future__ import annotations

from app.domain.enums import MusicFailureCode


def classify_ytdlp_music_error(message: str) -> MusicFailureCode:
    lowered = message.casefold()

    if "po token" in lowered or "visitor data" in lowered:
        return MusicFailureCode.PO_TOKEN_REQUIRED

    if any(
        marker in lowered
        for marker in (
            "login required",
            "sign in",
            "confirm you're not a bot",
            "use --cookies",
            "authentication required",
        )
    ):
        return MusicFailureCode.LOGIN_REQUIRED

    if any(
        marker in lowered
        for marker in (
            "requested format is not available",
            "no video formats found",
            "no suitable formats",
            "no formats",
        )
    ):
        return MusicFailureCode.NO_FORMATS

    if any(
        marker in lowered
        for marker in (
            "video unavailable",
            "private video",
            "this video is unavailable",
            "unavailable",
            "not available",
            "has been removed",
            "deleted",
        )
    ):
        return MusicFailureCode.SOURCE_UNAVAILABLE

    return MusicFailureCode.DOWNLOAD_FAILED
