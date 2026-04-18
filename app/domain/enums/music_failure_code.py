from enum import StrEnum


class MusicFailureCode(StrEnum):
    INVALID_QUERY = "invalid_query"
    RESOLVER_EMPTY = "resolver_empty"
    LOGIN_REQUIRED = "login_required"
    COOKIES_MISSING = "cookies_missing"
    COOKIES_SUSPECT = "cookies_suspect"
    PO_TOKEN_REQUIRED = "po_token_required"
    NO_FORMATS = "no_formats"
    SOURCE_UNAVAILABLE = "source_unavailable"
    ACQUISITION_EXHAUSTED = "acquisition_exhausted"
    DOWNLOAD_FAILED = "music_download_failed"
    TELEGRAM_CACHE_INVALID = "telegram_cache_invalid"


AUTH_RELATED_MUSIC_FAILURE_CODES = {
    MusicFailureCode.LOGIN_REQUIRED,
    MusicFailureCode.COOKIES_MISSING,
    MusicFailureCode.COOKIES_SUSPECT,
    MusicFailureCode.PO_TOKEN_REQUIRED,
}


def is_auth_related_music_failure(error_code: str) -> bool:
    try:
        code = MusicFailureCode(error_code)
    except ValueError:
        return False
    return code in AUTH_RELATED_MUSIC_FAILURE_CODES
