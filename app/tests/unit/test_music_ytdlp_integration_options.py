from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yt_dlp

from app.domain.errors import MusicDownloadError
from app.infrastructure.downloaders.audio_download_client import AudioDownloadClient
from app.infrastructure.providers.music.youtube_music_provider import YouTubeMusicProvider


def test_music_provider_search_passes_cookiefile_to_youtubedl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File", encoding="utf-8")
    captured: dict[str, object] = {}

    class DummyYDL:
        def __init__(self, options):
            captured["options"] = options

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url: str, download: bool = False):
            captured["url"] = url
            captured["download"] = download
            return {
                "_type": "playlist",
                "entries": [
                    {
                        "id": "abc123",
                        "title": "In the End",
                        "uploader": "Linkin Park",
                        "thumbnail": "https://img.example/abc123.jpg",
                        "duration": 216,
                    }
                ],
            }

    monkeypatch.setattr("app.infrastructure.providers.music.youtube_music_provider.yt_dlp.YoutubeDL", DummyYDL)

    provider = YouTubeMusicProvider(
        timeout_seconds=15,
        semaphore=asyncio.Semaphore(1),
    )

    info = provider._search("In the end Linkin Park", 1, cookies_file)

    assert info["_type"] == "playlist"
    assert captured["url"] == "ytsearch1:In the end Linkin Park"
    assert captured["download"] is False
    assert captured["options"]["cookiefile"] == str(cookies_file.resolve())
    assert captured["options"]["extract_flat"] is True


def test_music_audio_download_passes_cookiefile_to_youtubedl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File", encoding="utf-8")
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    captured: dict[str, object] = {}

    class DummyYDL:
        def __init__(self, options):
            captured["options"] = options

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url: str, download: bool = True):
            captured["url"] = url
            captured["download"] = download
            target_path = work_dir / "source.m4a"
            target_path.write_bytes(b"audio")
            return {"requested_downloads": [{"filepath": str(target_path)}]}

    monkeypatch.setattr("app.infrastructure.downloaders.audio_download_client.yt_dlp.YoutubeDL", DummyYDL)

    client = AudioDownloadClient(
        timeout_seconds=120,
        semaphore=asyncio.Semaphore(1),
        audio_only=True,
    )

    info = client._download_audio("https://www.youtube.com/watch?v=abc123", work_dir, cookies_file)

    assert info["requested_downloads"][0]["filepath"].endswith("source.m4a")
    assert captured["url"] == "https://www.youtube.com/watch?v=abc123"
    assert captured["download"] is True
    assert captured["options"]["cookiefile"] == str(cookies_file.resolve())


def test_music_audio_download_uses_minimal_robust_format_selector(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    captured: dict[str, object] = {}

    class DummyYDL:
        def __init__(self, options):
            captured["options"] = options

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url: str, download: bool = True):
            target_path = work_dir / "source.m4a"
            target_path.write_bytes(b"audio")
            return {"requested_downloads": [{"filepath": str(target_path)}]}

    monkeypatch.setattr("app.infrastructure.downloaders.audio_download_client.yt_dlp.YoutubeDL", DummyYDL)

    client = AudioDownloadClient(
        timeout_seconds=120,
        semaphore=asyncio.Semaphore(1),
        audio_only=True,
    )

    client._download_audio("https://www.youtube.com/watch?v=abc123", work_dir, None)

    assert captured["options"]["format"] == "best"
    assert "postprocessors" not in captured["options"]
    assert "merge_output_format" not in captured["options"]
    assert "format_sort" not in captured["options"]


def test_music_audio_download_raises_no_formats_with_minimal_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    captured: dict[str, object] = {}

    class DummyYDL:
        def __init__(self, options):
            captured["options"] = options

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url: str, download: bool = True):
            raise yt_dlp.utils.DownloadError("Requested format is not available")

    monkeypatch.setattr("app.infrastructure.downloaders.audio_download_client.yt_dlp.YoutubeDL", DummyYDL)

    client = AudioDownloadClient(
        timeout_seconds=120,
        semaphore=asyncio.Semaphore(1),
        audio_only=True,
    )

    with pytest.raises(MusicDownloadError) as exc_info:
        client._download_audio("https://www.youtube.com/watch?v=abc123", work_dir, None)

    assert captured["options"]["format"] == "best"
    assert exc_info.value.error_code == "no_formats"


def test_music_audio_download_format_selector_is_not_overly_strict() -> None:
    client = AudioDownloadClient(
        timeout_seconds=120,
        semaphore=asyncio.Semaphore(1),
        audio_only=True,
    )

    selector = client._build_format_selector()

    assert selector == "best"
    assert "[" not in selector
    assert selector not in {"bestaudio/best", "bestaudio"}
