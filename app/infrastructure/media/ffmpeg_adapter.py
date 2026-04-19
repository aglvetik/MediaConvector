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
            await self._run_ffmpeg(
                [
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
                ],
                normalized_key=normalized_key,
                operation="extract_audio",
            )
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
        cover_path: Path | None = None,
    ) -> Path:
        async with self._semaphore:
            command = [
                self._ffmpeg_path,
                "-nostdin",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source_path),
            ]
            if cover_path is not None:
                command.extend(["-i", str(cover_path)])
            command.extend(["-map", "0:a:0"])
            if cover_path is not None:
                command.extend(["-map", "1:v:0", "-c:v", "mjpeg", "-disposition:v", "attached_pic"])
            command.extend(["-c:a", "libmp3lame", "-q:a", "2", "-id3v2_version", "3"])
            if title:
                command.extend(["-metadata", f"title={_sanitize_metadata(title)}"])
            if performer:
                command.extend(["-metadata", f"artist={_sanitize_metadata(performer)}"])
            command.append(str(output_path))
            await self._run_ffmpeg(command, normalized_key=normalized_key, operation="transcode_audio")
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise AudioExtractionError("Audio output file is empty.")
            return output_path

    async def prepare_audio_thumbnail(
        self,
        source_path: Path,
        output_path: Path,
        *,
        normalized_key: str,
    ) -> Path:
        async with self._semaphore:
            await self._run_ffmpeg(
                [
                    self._ffmpeg_path,
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source_path),
                    "-vf",
                    "scale=320:320:force_original_aspect_ratio=decrease",
                    "-frames:v",
                    "1",
                    str(output_path),
                ],
                normalized_key=normalized_key,
                operation="prepare_audio_thumbnail",
            )
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise AudioExtractionError("Thumbnail output file is empty.")
            return output_path

    async def normalize_image_to_jpg(
        self,
        source_path: Path,
        output_path: Path,
        *,
        normalized_key: str,
    ) -> Path:
        async with self._semaphore:
            await self._run_ffmpeg(
                [
                    self._ffmpeg_path,
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(output_path),
                ],
                normalized_key=normalized_key,
                operation="normalize_image",
            )
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise AudioExtractionError("Normalized image output file is empty.")
            return output_path

    async def _run_ffmpeg(self, command: list[str], *, normalized_key: str, operation: str) -> None:
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
            raise AudioExtractionError("ffmpeg operation timed out.", context={"operation": operation}) from exc

        stderr_text = stderr.decode("utf-8", errors="ignore")
        if process.returncode != 0:
            lower = stderr_text.lower()
            if operation in {"extract_audio", "transcode_audio"} and (
                "output file is empty" in lower or "matches no streams" in lower or "does not contain any stream" in lower
            ):
                raise AudioExtractionError("Source video has no audio track.", no_audio_track=True)
            raise AudioExtractionError("ffmpeg failed to process media.", context={"stderr": stderr_text, "operation": operation})


def _sanitize_metadata(value: str) -> str:
    return " ".join(value.replace("\n", " ").replace("\r", " ").split()).strip()
