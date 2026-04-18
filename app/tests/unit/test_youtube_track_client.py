from __future__ import annotations

import asyncio
from pathlib import Path

from app.infrastructure.downloaders.youtube_track_client import YoutubeTrackClient


def test_youtube_track_client_includes_cookiefile_when_configured(tmp_path: Path) -> None:
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File", encoding="utf-8")
    client = YoutubeTrackClient(
        timeout_seconds=30,
        semaphore=asyncio.Semaphore(1),
        cookies_file=cookies_file,
    )

    options = client._build_options(download=False, work_dir=None, operation="track_search")

    assert options["cookiefile"] == str(cookies_file)


def test_youtube_track_client_omits_cookiefile_when_not_configured(tmp_path: Path) -> None:
    client = YoutubeTrackClient(
        timeout_seconds=30,
        semaphore=asyncio.Semaphore(1),
        cookies_file=None,
    )

    options = client._build_options(download=True, work_dir=tmp_path, operation="track_download")

    assert "cookiefile" not in options


def test_youtube_track_client_omits_cookiefile_when_missing(tmp_path: Path) -> None:
    client = YoutubeTrackClient(
        timeout_seconds=30,
        semaphore=asyncio.Semaphore(1),
        cookies_file=tmp_path / "missing-cookies.txt",
    )

    options = client._build_options(download=True, work_dir=tmp_path, operation="track_download")

    assert "cookiefile" not in options
