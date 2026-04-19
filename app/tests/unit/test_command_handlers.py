from __future__ import annotations

from app.presentation.telegram.handlers.command_handlers import _help_text, _start_text


def test_start_text_is_short_and_non_technical() -> None:
    text = _start_text()

    assert "TikTok" in text
    assert "YouTube" in text
    assert "групп" in text.casefold()
    for forbidden in ("yt-dlp", "gallery-dl", "extractor", "engine", "pipeline", "normalization", "audio-first"):
        assert forbidden not in text.casefold()


def test_help_text_is_short_and_non_technical() -> None:
    text = _help_text()

    assert "видео" in text.casefold()
    assert "фото" in text.casefold()
    assert "аудио" in text.casefold()
    for forbidden in ("yt-dlp", "gallery-dl", "extractor", "engine", "pipeline", "normalization", "audio-first"):
        assert forbidden not in text.casefold()
