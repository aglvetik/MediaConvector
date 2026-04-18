from __future__ import annotations

import asyncio
import logging
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

    async def transcode_audio_to_mp3(
        self,
        source_path: Path,
        output_path: Path,
        *,
        normalized_key: str,
        title: str | None = None,
        performer: str | None = None,
    ) -> Path:
        command = [
            self._ffmpeg_path,
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
        ]
        if title:
            command.extend(["-metadata", f"title={title}"])
        if performer:
            command.extend(["-metadata", f"artist={performer}"])
        command.append(str(output_path))
        return await self._run_ffmpeg(
            command,
            normalized_key=normalized_key,
            started_event="music_audio_transcode_started",
            finished_event="music_audio_transcode_finished",
            input_file=source_path,
            output_file=output_path,
        )

    async def prepare_thumbnail(self, source_path: Path, output_path: Path, *, normalized_key: str) -> Path:
        command = [
            self._ffmpeg_path,
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source_path),
            "-vf",
            "scale='min(320,iw)':'min(320,ih)':force_original_aspect_ratio=decrease",
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(output_path),
        ]
        return await self._run_ffmpeg(
            command,
            normalized_key=normalized_key,
            started_event="music_thumbnail_prepare_started",
            finished_event="music_thumbnail_prepare_finished",
            input_file=source_path,
            output_file=output_path,
        )

    async def _run_ffmpeg(
        self,
        command: list[str],
        *,
        normalized_key: str,
        started_event: str,
        finished_event: str,
        input_file: Path,
        output_file: Path,
    ) -> Path:
        async with self._semaphore:
            log_event(self._logger, logging.INFO, started_event, normalized_key=normalized_key, input_file=str(input_file))
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
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
                raise AudioExtractionError("ffmpeg processing timed out.") from exc

            stderr_text = stderr.decode("utf-8", errors="ignore")
            if process.returncode != 0:
                raise AudioExtractionError("ffmpeg processing failed.", context={"stderr": stderr_text})
            if not output_file.exists() or output_file.stat().st_size == 0:
                raise AudioExtractionError("ffmpeg output file is empty.", context={"output_file": str(output_file)})

            log_event(
                self._logger,
                logging.INFO,
                finished_event,
                normalized_key=normalized_key,
                output_file=str(output_file),
                output_size_bytes=output_file.stat().st_size,
            )
            return output_file
