from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    bot_mode: Literal["polling", "webhook"] = Field(default="polling", alias="BOT_MODE")
    database_url: str = Field(default="sqlite+aiosqlite:///runtime/bot.db", alias="DATABASE_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    temp_dir: Path = Field(default=Path("runtime/tmp"), alias="TEMP_DIR")
    max_parallel_downloads: int = Field(default=2, alias="MAX_PARALLEL_DOWNLOADS")
    max_parallel_ffmpeg: int = Field(default=2, alias="MAX_PARALLEL_FFMPEG")
    max_file_size_mb: int = Field(default=45, alias="MAX_FILE_SIZE_MB")
    request_timeout_seconds: int = Field(default=20, alias="REQUEST_TIMEOUT_SECONDS")
    download_timeout_seconds: int = Field(default=120, alias="DOWNLOAD_TIMEOUT_SECONDS")
    ffmpeg_path: str = Field(default="ffmpeg", alias="FFMPEG_PATH")
    ytdlp_path: str = Field(default="yt-dlp", alias="YTDLP_PATH")
    ytdlp_cookies_file: Path | None = Field(default=None, alias="YTDLP_COOKIES_FILE")
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    user_requests_per_minute: int = Field(default=4, alias="USER_REQUESTS_PER_MINUTE")
    user_request_cooldown_seconds: int = Field(default=3, alias="USER_REQUEST_COOLDOWN_SECONDS")
    max_music_query_length: int = Field(default=120, alias="MAX_MUSIC_QUERY_LENGTH")
    music_search_timeout_seconds: int = Field(default=15, alias="MUSIC_SEARCH_TIMEOUT_SECONDS")
    music_resolver_max_candidates: int = Field(default=3, alias="MUSIC_RESOLVER_MAX_CANDIDATES")
    music_strategy_order: str = Field(default="youtube_cookies,youtube_no_cookies", alias="MUSIC_STRATEGY_ORDER")
    music_resolver_order: str | None = Field(default=None, alias="MUSIC_RESOLVER_ORDER")
    music_download_provider_order: str = Field(
        default="remote_http,youtube_cookies,youtube_no_cookies",
        alias="MUSIC_DOWNLOAD_PROVIDER_ORDER",
    )
    music_remote_provider_url: str | None = Field(default=None, alias="MUSIC_REMOTE_PROVIDER_URL")
    music_remote_provider_token: str | None = Field(default=None, alias="MUSIC_REMOTE_PROVIDER_TOKEN")
    music_remote_provider_timeout_seconds: int = Field(default=30, alias="MUSIC_REMOTE_PROVIDER_TIMEOUT_SECONDS")
    youtube_auth_fail_threshold: int = Field(default=2, alias="YOUTUBE_AUTH_FAIL_THRESHOLD")
    youtube_degrade_ttl_minutes: int = Field(default=30, alias="YOUTUBE_DEGRADE_TTL_MINUTES")
    music_audio_only: bool = Field(default=True, alias="MUSIC_AUDIO_ONLY")
    cookie_healthcheck_enabled: bool = Field(default=True, alias="COOKIE_HEALTHCHECK_ENABLED")
    temp_file_ttl_minutes: int = Field(default=30, alias="TEMP_FILE_TTL_MINUTES")
    cleanup_interval_minutes: int = Field(default=10, alias="CLEANUP_INTERVAL_MINUTES")
    health_interval_minutes: int = Field(default=15, alias="HEALTH_INTERVAL_MINUTES")
    job_stale_after_minutes: int = Field(default=15, alias="JOB_STALE_AFTER_MINUTES")

    @field_validator(
        "max_parallel_downloads",
        "max_parallel_ffmpeg",
        "user_requests_per_minute",
        "user_request_cooldown_seconds",
        "max_music_query_length",
        "music_search_timeout_seconds",
        "music_resolver_max_candidates",
        "music_remote_provider_timeout_seconds",
        "youtube_auth_fail_threshold",
    )
    @classmethod
    def _positive_ints(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Concurrency and rate-limit values must be >= 1.")
        return value

    @field_validator(
        "youtube_degrade_ttl_minutes",
        "temp_file_ttl_minutes",
        "cleanup_interval_minutes",
        "health_interval_minutes",
        "job_stale_after_minutes",
    )
    @classmethod
    def _positive_time_values(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Time interval values must be >= 1 minute.")
        return value

    @field_validator("ytdlp_cookies_file", mode="before")
    @classmethod
    def _empty_cookie_path_to_none(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "music_resolver_order",
        "music_remote_provider_url",
        "music_remote_provider_token",
        mode="before",
    )
    @classmethod
    def _empty_string_to_none(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def sync_database_url(self) -> str:
        if self.database_url.startswith("sqlite+aiosqlite:///"):
            return self.database_url.replace("sqlite+aiosqlite:///", "sqlite:///")
        return self.database_url

    def ensure_runtime_dirs(self) -> None:
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        database_path = self.database_path
        if database_path is not None:
            database_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def database_path(self) -> Path | None:
        url = make_url(self.sync_database_url)
        if not url.drivername.startswith("sqlite") or url.database in {None, "", ":memory:"}:
            return None
        database_path = Path(url.database)
        if database_path.is_absolute():
            return database_path
        return Path.cwd() / database_path

    @property
    def music_strategy_order_list(self) -> tuple[str, ...]:
        return self._parse_csv_order(self.music_strategy_order, default=("youtube_cookies", "youtube_no_cookies"))

    @property
    def music_resolver_order_list(self) -> tuple[str, ...]:
        source = self.music_resolver_order or self.music_strategy_order
        return self._parse_csv_order(source, default=("youtube_cookies", "youtube_no_cookies"))

    @property
    def music_download_provider_order_list(self) -> tuple[str, ...]:
        return self._parse_csv_order(
            self.music_download_provider_order,
            default=("remote_http", "youtube_cookies", "youtube_no_cookies"),
        )

    @property
    def resolved_ytdlp_cookies_file(self) -> Path | None:
        if self.ytdlp_cookies_file is None:
            return None
        cookies_path = self.ytdlp_cookies_file.expanduser()
        if not cookies_path.is_absolute():
            cookies_path = _PROJECT_ROOT / cookies_path
        return cookies_path.resolve(strict=False)

    @staticmethod
    def _parse_csv_order(value: str | None, *, default: tuple[str, ...]) -> tuple[str, ...]:
        if value is None:
            return default
        values = tuple(
            part.strip().lower()
            for part in value.split(",")
            if part.strip()
        )
        if values:
            return values
        return default


def load_settings() -> Settings:
    settings = Settings()
    settings.ensure_runtime_dirs()
    return settings
