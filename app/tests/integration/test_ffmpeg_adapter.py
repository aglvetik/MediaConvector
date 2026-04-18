import asyncio
from pathlib import Path

import pytest

from app.domain.errors import AudioExtractionError
from app.infrastructure.media.ffmpeg_adapter import FfmpegAdapter


class DummyProcess:
    def __init__(self, *, returncode: int, stderr: bytes) -> None:
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self):
        return b"", self._stderr

    def kill(self) -> None:
        return None


@pytest.mark.asyncio
async def test_ffmpeg_adapter_success(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "audio.mp3"

    async def fake_create_subprocess_exec(*args, **kwargs):
        output.write_bytes(b"audio")
        return DummyProcess(returncode=0, stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    adapter = FfmpegAdapter(ffmpeg_path="ffmpeg", timeout_seconds=5, semaphore=asyncio.Semaphore(1))
    result = await adapter.extract_audio(tmp_path / "video.mp4", output, normalized_key="tiktok:video:1")
    assert result == output


@pytest.mark.asyncio
async def test_ffmpeg_adapter_detects_no_audio(monkeypatch, tmp_path: Path) -> None:
    async def fake_create_subprocess_exec(*args, **kwargs):
        return DummyProcess(returncode=1, stderr=b"Output file is empty")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    adapter = FfmpegAdapter(ffmpeg_path="ffmpeg", timeout_seconds=5, semaphore=asyncio.Semaphore(1))
    with pytest.raises(AudioExtractionError) as exc_info:
        await adapter.extract_audio(tmp_path / "video.mp4", tmp_path / "audio.mp3", normalized_key="tiktok:video:1")
    assert exc_info.value.error_code == "no_audio_track"


@pytest.mark.asyncio
async def test_ffmpeg_adapter_transcodes_audio_and_thumbnail(monkeypatch, tmp_path: Path) -> None:
    mp3_output = tmp_path / "track.mp3"
    jpg_output = tmp_path / "thumb.jpg"

    async def fake_create_subprocess_exec(*args, **kwargs):
        command = list(args)
        destination = Path(command[-1])
        destination.write_bytes(b"media")
        return DummyProcess(returncode=0, stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    adapter = FfmpegAdapter(ffmpeg_path="ffmpeg", timeout_seconds=5, semaphore=asyncio.Semaphore(1))
    source_audio = tmp_path / "source.webm"
    source_audio.write_bytes(b"audio")
    source_image = tmp_path / "source.webp"
    source_image.write_bytes(b"image")

    result_audio = await adapter.transcode_audio_to_mp3(
        source_audio,
        mp3_output,
        normalized_key="tiktok:audio:test",
        title="Track",
        performer="Artist",
        cover_path=source_image,
    )
    result_thumbnail = await adapter.prepare_audio_thumbnail(
        source_image,
        jpg_output,
        normalized_key="tiktok:audio:test",
    )
    assert result_audio == mp3_output
    assert result_thumbnail == jpg_output
