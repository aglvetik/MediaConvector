from __future__ import annotations

import asyncio
from pathlib import Path

from app.domain.errors import AudioExtractionError
from app.infrastructure.logging import get_logger, log_event


class FfmpegAdapter:
    def __init__(self, *, ffmpeg_path: str, timeout_seconds: int, semaphore: asyncio.Semaphore) -> None:
        self._ffmpeg_path = ffmpeg_path
        self._timeout_seconds = timeout_seconds
        self._semaphore = semaphore
        self._logger = get_logger(__name__)

    async def extract_audio(self, video_path: Path, output_path: Path, *, normalized_key: str) -> Path:
        async with self._semaphore:
            log_event(self._logger, 20, "audio_extract_started", normalized_key=normalized_key, input_file=str(video_path))
            try:
                process = await asyncio.create_subprocess_exec(
                    self._ffmpeg_path,
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(video_path),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-c:a",
                    "libmp3lame",
                    "-q:a",
                    "2",
                    str(output_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                raise AudioExtractionError("ffmpeg binary was not found.", context={"ffmpeg_path": self._ffmpeg_path}) from exc
            try:
                _, stderr = await asyncio.wait_for(process.communicate(), timeout=self._timeout_seconds)
            except TimeoutError as exc:
                process.kill()
                await process.communicate()
                raise AudioExtractionError("ffmpeg audio extraction timed out.") from exc

            stderr_text = stderr.decode("utf-8", errors="ignore")
            if process.returncode != 0:
                lower = stderr_text.lower()
                if "output file is empty" in lower or "matches no streams" in lower or "does not contain any stream" in lower:
                    raise AudioExtractionError("Source video has no audio track.", no_audio_track=True)
                raise AudioExtractionError("ffmpeg failed to extract audio.", context={"stderr": stderr_text})

            if not output_path.exists() or output_path.stat().st_size == 0:
                raise AudioExtractionError("Audio output file is empty.", no_audio_track=True)

            log_event(
                self._logger,
                20,
                "audio_extract_finished",
                normalized_key=normalized_key,
                output_file=str(output_path),
                audio_size_bytes=output_path.stat().st_size,
            )
            return output_path
