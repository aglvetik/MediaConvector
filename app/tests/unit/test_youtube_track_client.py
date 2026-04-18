from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.domain.errors import TrackDownloadError
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


@pytest.mark.asyncio
async def test_youtube_track_client_falls_back_across_format_selectors(tmp_path: Path) -> None:
    client = YoutubeTrackClient(
        timeout_seconds=30,
        semaphore=asyncio.Semaphore(1),
    )
    attempted_selectors: list[str | None] = []
    target_path = tmp_path / "downloaded.bin"

    def fake_extract_info(
        url: str,
        download: bool,
        work_dir: Path | None,
        operation: str,
        format_selector: str | None = "bestaudio/best",
    ) -> dict[str, object]:
        attempted_selectors.append(format_selector)
        if format_selector in {"bestaudio/best", "best"}:
            raise TrackDownloadError(
                "Requested format is not available. Use --list-formats for a list of available formats",
                context={"format_unavailable": True},
            )
        target_path.write_bytes(b"downloaded")
        return {"filepath": str(target_path)}

    client._extract_info = fake_extract_info  # type: ignore[method-assign]

    result = await client.download_audio(
        "https://www.youtube.com/watch?v=test123",
        tmp_path,
        normalized_key="music:track:test123",
    )

    assert attempted_selectors == ["bestaudio/best", "best", None]
    assert result == target_path
