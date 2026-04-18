from __future__ import annotations

from app.config import Settings


def test_settings_load_with_minimal_required_env(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:test-token")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TEMP_DIR", raising=False)

    settings = Settings(_env_file=None)

    assert settings.bot_token == "123:test-token"
    assert settings.bot_mode == "polling"
    assert settings.database_url == "sqlite+aiosqlite:///runtime/bot.db"
    assert settings.temp_dir.name == "tmp"
    assert settings.user_request_cooldown_seconds == 3
    assert settings.ffmpeg_path == "ffmpeg"
    assert settings.ytdlp_path == "yt-dlp"
