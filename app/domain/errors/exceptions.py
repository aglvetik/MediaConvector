from __future__ import annotations

from dataclasses import dataclass, field

from app import messages


@dataclass(slots=True)
class AppError(Exception):
    message: str
    user_message: str
    error_code: str
    context: dict[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


class UnsupportedUrlError(AppError):
    def __init__(self, message: str = "Unsupported or missing TikTok URL.") -> None:
        super().__init__(message=message, user_message=messages.INVALID_TIKTOK_LINK, error_code="unsupported_url")


class NormalizationError(AppError):
    def __init__(self, message: str, *, context: dict[str, object] | None = None) -> None:
        super().__init__(
            message=message,
            user_message=messages.INVALID_TIKTOK_LINK,
            error_code="normalization_failed",
            context=context or {},
        )


class DownloadError(AppError):
    def __init__(self, message: str, *, temporary: bool = True, context: dict[str, object] | None = None) -> None:
        super().__init__(
            message=message,
            user_message=messages.TEMPORARY_DOWNLOAD_ERROR if temporary else messages.VIDEO_UNAVAILABLE,
            error_code="download_failed",
            context=context or {},
        )


class DownloadUnavailableError(AppError):
    def __init__(self, message: str = "Video is unavailable.") -> None:
        super().__init__(message=message, user_message=messages.VIDEO_UNAVAILABLE, error_code="video_unavailable")


class AudioExtractionError(AppError):
    def __init__(self, message: str, *, no_audio_track: bool = False, context: dict[str, object] | None = None) -> None:
        super().__init__(
            message=message,
            user_message=messages.NO_AUDIO_TRACK if no_audio_track else messages.AUDIO_EXTRACTION_FAILED,
            error_code="audio_extract_failed" if not no_audio_track else "no_audio_track",
            context=context or {},
        )


class TelegramDeliveryError(AppError):
    def __init__(self, message: str, *, user_message: str | None = None, context: dict[str, object] | None = None) -> None:
        super().__init__(
            message=message,
            user_message=user_message or messages.UNKNOWN_ERROR,
            error_code="telegram_delivery_failed",
            context=context or {},
        )


class BotForbiddenError(AppError):
    def __init__(self, message: str = "Bot cannot send messages to this chat.") -> None:
        super().__init__(message=message, user_message=messages.BOT_CANNOT_SEND, error_code="bot_forbidden")


class MediaTooLargeError(AppError):
    def __init__(self, message: str = "Media file exceeds Telegram upload limits.") -> None:
        super().__init__(message=message, user_message=messages.FILE_TOO_LARGE, error_code="file_too_large")


class InvalidCachedMediaError(AppError):
    def __init__(
        self,
        message: str,
        *,
        media_kind: str,
        video_sent: bool = False,
        context: dict[str, object] | None = None,
    ) -> None:
        payload = {"media_kind": media_kind, "video_sent": video_sent}
        payload.update(context or {})
        super().__init__(
            message=message,
            user_message=messages.TEMPORARY_DOWNLOAD_ERROR,
            error_code="invalid_cached_media",
            context=payload,
        )


class RateLimitExceededError(AppError):
    def __init__(self, message: str = "Per-user rate limit exceeded.") -> None:
        super().__init__(message=message, user_message=messages.RATE_LIMIT_EXCEEDED, error_code="rate_limit_exceeded")


class ProcessingConflictError(AppError):
    def __init__(self, message: str = "Message already processed.") -> None:
        super().__init__(message=message, user_message="", error_code="processing_conflict")


class MusicQueryValidationError(AppError):
    def __init__(self, message: str, *, user_message: str, context: dict[str, object] | None = None) -> None:
        super().__init__(
            message=message,
            user_message=user_message,
            error_code="music_query_invalid",
            context=context or {},
        )


class MusicNotFoundError(AppError):
    def __init__(self, message: str = "No track search results.") -> None:
        super().__init__(message=message, user_message=messages.MUSIC_NOT_FOUND, error_code="music_not_found")


class MusicDownloadError(AppError):
    def __init__(self, message: str, *, context: dict[str, object] | None = None) -> None:
        super().__init__(
            message=message,
            user_message=messages.MUSIC_DOWNLOAD_FAILED,
            error_code="music_download_failed",
            context=context or {},
        )
