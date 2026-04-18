from __future__ import annotations

from app.config import Settings


def test_settings_load_with_minimal_required_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:test-token")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TEMP_DIR", raising=False)

    settings = Settings(_env_file=None)

    assert settings.bot_token == "123:test-token"
    assert settings.bot_mode == "polling"
    assert settings.database_url == "sqlite+aiosqlite:///runtime/bot.db"
    assert settings.temp_dir.name == "tmp"
    assert settings.user_request_cooldown_seconds == 3
    assert settings.max_music_query_length == 120
    assert settings.music_search_timeout_seconds == 15
    assert settings.music_resolver_max_candidates == 3
    assert settings.music_strategy_order_list == ("jamendo", "internet_archive")
    assert settings.music_resolver_order_list == ("jamendo", "internet_archive")
    assert settings.music_download_provider_order_list == ("jamendo", "internet_archive")
    assert settings.jamendo_client_id is None
    assert settings.jamendo_timeout_seconds == 15
    assert settings.internet_archive_timeout_seconds == 20
    assert settings.youtube_auth_fail_threshold == 2
    assert settings.youtube_degrade_ttl_minutes == 30
    assert settings.music_audio_only is True
    assert settings.cookie_healthcheck_enabled is True
    assert settings.ytdlp_cookies_file is None


def test_settings_treats_empty_cookies_path_as_none(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:test-token")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", "")

    settings = Settings(_env_file=None)

    assert settings.ytdlp_cookies_file is None
    assert settings.resolved_ytdlp_cookies_file is None


def test_settings_parse_legal_provider_order_overrides(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:test-token")
    monkeypatch.setenv("MUSIC_RESOLVER_ORDER", "internet_archive,jamendo")
    monkeypatch.setenv("MUSIC_DOWNLOAD_PROVIDER_ORDER", "internet_archive,jamendo")

    settings = Settings(_env_file=None)

    assert settings.music_resolver_order_list == ("internet_archive", "jamendo")
    assert settings.music_download_provider_order_list == ("internet_archive", "jamendo")
