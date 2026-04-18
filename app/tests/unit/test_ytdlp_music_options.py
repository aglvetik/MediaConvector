from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.domain.errors import MusicDownloadError
from app.infrastructure.downloaders.ytdlp_music_options import build_music_ytdlp_options


def test_build_music_ytdlp_options_without_cookies() -> None:
    logger = logging.getLogger("test-ytdlp-options")
    options = build_music_ytdlp_options(
        {"quiet": True, "noplaylist": True},
        cookies_file=None,
        logger=logger,
        operation="music_search",
    )
    assert options == {"quiet": True, "noplaylist": True}
    assert "cookiefile" not in options


def test_build_music_ytdlp_options_with_existing_cookies_file(tmp_path: Path) -> None:
    logger = logging.getLogger("test-ytdlp-options")
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File", encoding="utf-8")

    options = build_music_ytdlp_options(
        {"quiet": True},
        cookies_file=cookies_file,
        logger=logger,
        operation="music_download",
    )

    assert options["quiet"] is True
    assert options["cookiefile"] == str(cookies_file.resolve())


def test_build_music_ytdlp_options_with_missing_cookies_file_logs_and_fails(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    logger = logging.getLogger("test-ytdlp-options")
    missing_file = tmp_path / "missing-cookies.txt"

    with caplog.at_level(logging.ERROR):
        with pytest.raises(MusicDownloadError) as exc_info:
            build_music_ytdlp_options(
                {"quiet": True},
                cookies_file=missing_file,
                logger=logger,
                operation="music_search",
            )

    assert exc_info.value.error_code == "music_download_failed"
    assert any(record.msg == "music_ytdlp_cookies_missing" for record in caplog.records)
