from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


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
    gallerydl_path: str = Field(default="gallery-dl", alias="GALLERYDL_PATH")
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    user_requests_per_minute: int = Field(default=4, alias="USER_REQUESTS_PER_MINUTE")
    user_request_cooldown_seconds: int = Field(default=3, alias="USER_REQUEST_COOLDOWN_SECONDS")
    temp_file_ttl_minutes: int = Field(default=30, alias="TEMP_FILE_TTL_MINUTES")
    cleanup_interval_minutes: int = Field(default=10, alias="CLEANUP_INTERVAL_MINUTES")
    health_interval_minutes: int = Field(default=15, alias="HEALTH_INTERVAL_MINUTES")
    job_stale_after_minutes: int = Field(default=15, alias="JOB_STALE_AFTER_MINUTES")

    @field_validator(
        "max_parallel_downloads",
        "max_parallel_ffmpeg",
        "user_requests_per_minute",
        "user_request_cooldown_seconds",
    )
    @classmethod
    def _positive_ints(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Concurrency and rate-limit values must be >= 1.")
        return value

    @field_validator(
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


def load_settings() -> Settings:
    settings = Settings()
    settings.ensure_runtime_dirs()
    return settings
