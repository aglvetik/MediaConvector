from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.domain.entities.normalized_resource import NormalizedResource
from app.domain.enums.platform import Platform
from app.domain.errors import DownloadError
from app.infrastructure.downloaders.ytdlp_client import YtDlpClient


@pytest.mark.asyncio
async def test_ytdlp_client_video_download_falls_back_across_format_selectors(tmp_path: Path) -> None:
    client = YtDlpClient(
        binary_path="yt-dlp",
        timeout_seconds=10,
        semaphore=asyncio.Semaphore(1),
    )
    normalized = NormalizedResource(
        platform=Platform.TIKTOK,
        resource_type="video",
        resource_id="abc123",
        normalized_key="tiktok:video:abc123",
        original_url="https://www.tiktok.com/@user/video/abc123",
        canonical_url="https://www.tiktok.com/@user/video/abc123",
    )
    attempted_selectors: list[str | None] = []

    def fake_extract_info(
        url: str,
        download: bool,
        work_dir: Path | None,
        format_selector: str | None = "bestvideo+bestaudio/best",
        merge_output_format: str | None = "mp4",
        extra_options: dict[str, object] | None = None,
    ) -> dict[str, object]:
        del url, download, merge_output_format, extra_options
        attempted_selectors.append(format_selector)
        if format_selector in {"bv*+ba/b", "bestvideo+bestaudio/best"}:
            raise DownloadError(
                "Requested format is not available.",
                temporary=True,
                context={"format_unavailable": True, "format_selector": format_selector},
            )
        target = work_dir / "downloaded.mp4"
        target.write_bytes(b"video")
        return {"filepath": str(target), "title": "Demo", "uploader": "Channel", "acodec": "mp4a.40.2"}

    client._extract_info = fake_extract_info  # type: ignore[method-assign]

    path, metadata = await client.download_video(normalized, tmp_path)

    assert path.name == "downloaded.mp4"
    assert metadata.title == "Demo"
    assert attempted_selectors == ["bv*+ba/b", "bestvideo+bestaudio/best", "best"]


@pytest.mark.asyncio
async def test_ytdlp_client_audio_download_falls_back_across_audio_selectors(tmp_path: Path) -> None:
    client = YtDlpClient(
        binary_path="yt-dlp",
        timeout_seconds=10,
        semaphore=asyncio.Semaphore(1),
    )
    attempted_selectors: list[str | None] = []

    def fake_extract_info(
        url: str,
        download: bool,
        work_dir: Path | None,
        format_selector: str | None = "bestvideo+bestaudio/best",
        merge_output_format: str | None = "mp4",
        extra_options: dict[str, object] | None = None,
    ) -> dict[str, object]:
        del url, download, merge_output_format, extra_options
        attempted_selectors.append(format_selector)
        if format_selector == "bestaudio/best":
            raise DownloadError(
                "Requested format is not available.",
                temporary=True,
                context={"format_unavailable": True, "format_selector": format_selector},
            )
        target = work_dir / "downloaded.m4a"
        target.write_bytes(b"audio")
        return {"filepath": str(target), "title": "Demo", "uploader": "Channel", "acodec": "mp4a.40.2"}

    client._extract_info = fake_extract_info  # type: ignore[method-assign]

    path, metadata = await client.download_audio(
        "https://www.tiktok.com/@user/video/abc123",
        tmp_path,
        normalized_key="tiktok:video:abc123",
    )

    assert path.name == "downloaded.m4a"
    assert metadata.title == "Demo"
    assert attempted_selectors == ["bestaudio/best", "best"]
